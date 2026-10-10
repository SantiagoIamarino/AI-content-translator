import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import tracemalloc
import unittest
from unittest.mock import patch

import numpy as np
import soundfile as sf

from aidub.asr_client import AsrClient
from aidub.batches import invoke_batches, request_batches
from aidub.config import load_config
from aidub.energy import EnergyIndex, rolling_mask
from aidub.export import place_voice
from aidub.handoff import translation_request
from aidub.job import Job, JobLock
from aidub.ledger import checkpoint_matches
from aidub.media import describe_streams, frame_check, probe, validate_container, video_packet_span
from aidub.pipeline import _LineAssessor, run_job, stage_inspect, stage_extract, stage_mix, stage_validate
from aidub.providers import ProviderError, invoke_checked
from aidub.quality import assess_candidate, speaker_profile
from aidub.schedule import synth_cache_key
from aidub.segment import build_segments, build_segments_file
from aidub.streaming import alignment_meta, stream_mix, validate_audio_files
from aidub.transcription import transcribe_chunks, owned_segments
from aidub.util import fingerprint, read_json, write_json
from aidub.verification import verification_identity


def request(n=1):
    return translation_request('job', [{'id': i + 1, 'spanish': f'Hola {i}', 'start': i * 2, 'end': i * 2 + 1,
                              'anchor_type': 'utterance'} for i in range(n)], n * 2 + 1)


def response(req):
    return {'schema': 'aidub.translation_response.v1', 'job_id': req['job_id'], 'translator': {'kind': 'command'},
            'segments': [{'id': row['id'], 'english': f"Hello {row['id']}"} for row in req['segments']]}


class ProviderRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.req, self.res = self.root / 'request.json', self.root / 'response.json'
        write_json(self.req, request())
        self.spec = {'kind': 'command', 'command': [sys.executable]}

    def tearDown(self):
        self.tmp.cleanup()

    def fake(self, spec, req, res, role):
        data = response(read_json(req))
        write_json(res, data)
        return data

    def test_response_before_acceptance_interruption_is_reused(self):
        def interrupted(*args):
            self.fake(*args)
            raise KeyboardInterrupt('crash after durable response')
        with patch('aidub.providers.invoke_provider', side_effect=interrupted) as call:
            with self.assertRaises(KeyboardInterrupt):
                invoke_checked(self.spec, self.req, self.res, 'translation')
            self.assertEqual(call.call_count, 1)
        with patch('aidub.providers.invoke_provider', side_effect=AssertionError('must not call provider')):
            recovered = invoke_checked(self.spec, self.req, self.res, 'translation', before_invoke=lambda: (_ for _ in ()).throw(RuntimeError('GPU unavailable')))
        self.assertEqual(recovered['segments'][0]['english'], 'Hello 1')

    def test_request_changes_never_reuse_another_response_and_old_identity_is_recoverable(self):
        with patch('aidub.providers.invoke_provider', side_effect=self.fake) as call:
            a = invoke_checked(self.spec, self.req, self.res, 'translation')
            changed = request(); changed['segments'][0]['spanish'] = 'Otro texto'
            write_json(self.req, changed)
            invoke_checked(self.spec, self.req, self.res, 'translation')
            write_json(self.req, request())
            self.assertEqual(invoke_checked(self.spec, self.req, self.res, 'translation'), a)
            self.assertEqual(call.call_count, 2)

    def test_corrupt_canonical_response_recovers_saved_attempt_without_new_call(self):
        with patch('aidub.providers.invoke_provider', side_effect=self.fake):
            expected = invoke_checked(self.spec, self.req, self.res, 'translation')
        self.res.write_text('{incomplete')
        with patch('aidub.providers.invoke_provider', side_effect=AssertionError('paid call repeated')):
            self.assertEqual(invoke_checked(self.spec, self.req, self.res, 'translation'), expected)

    def test_feedback_is_in_retry_json_for_any_provider(self):
        calls = []
        def fake(spec, req, res, role):
            doc = read_json(req); calls.append(doc)
            data = response(doc)
            if len(calls) == 1:
                data['segments'] = []
            else:
                self.assertIn('missing ids', ' '.join(doc['validation_feedback']['errors']))
            write_json(res, data)
            return data
        with patch('aidub.providers.invoke_provider', side_effect=fake):
            invoke_checked(self.spec, self.req, self.res, 'translation')
        self.assertEqual(len(calls), 2)

    def test_missing_durable_response_records_uncertain_outcome(self):
        with patch('aidub.providers.invoke_provider', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                invoke_checked(self.spec, self.req, self.res, 'translation')
        with patch('aidub.providers.invoke_provider', side_effect=self.fake):
            invoke_checked(self.spec, self.req, self.res, 'translation')
        state = read_json(next(self.root.glob('response_attempts/*/state.json')))
        self.assertEqual(state['attempts'][0]['status'], 'outcome_uncertain')
        self.assertTrue(state['uncertain_outcomes'])

    def test_timeout_is_bounded_persisted_and_does_not_repeat_on_resume(self):
        script = self.root / 'slow.py'; script.write_text('import time; time.sleep(30)')
        spec = {'kind': 'command', 'command': [sys.executable, str(script)], 'timeout_sec': 0.1, 'max_attempts': 1}
        started = time.monotonic()
        with self.assertRaisesRegex(ProviderError, 'uncertain'):
            invoke_checked(spec, self.req, self.res, 'translation')
        self.assertLess(time.monotonic() - started, 3)
        with patch('aidub.providers.invoke_provider', side_effect=AssertionError('budget exhausted')):
            with self.assertRaisesRegex(ProviderError, 'exhausted 1'):
                invoke_checked(spec, self.req, self.res, 'translation')
        # Raising the attempt budget must retain the identity and its existing attempt.
        spec['max_attempts'] = 2
        with patch('aidub.providers.invoke_provider', side_effect=self.fake):
            invoke_checked(spec, self.req, self.res, 'translation')
        state = read_json(next(self.root.glob('response_attempts/*/state.json')))
        self.assertEqual(len(state['attempts']), 2)

    def test_batches_resume_without_repeating_accepted_batches(self):
        seen = []
        def interrupted(spec, req, res, role):
            doc = read_json(req); seen.append([s['id'] for s in doc['segments']])
            if len(seen) == 2:
                raise KeyboardInterrupt('between batches')
            return self.fake(spec, req, res, role)
        cfg = {'batching': {'max_cues': 2, 'max_chars': 10000}}
        with patch('aidub.providers.invoke_provider', side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt):
                invoke_batches(self.spec, request(5), self.root, 'translation', None, cfg)
        with patch('aidub.providers.invoke_provider', side_effect=self.fake) as call:
            result = invoke_batches(self.spec, request(5), self.root, 'translation', None, cfg)
            self.assertEqual(call.call_count, 2)
        self.assertEqual([r['id'] for r in result['segments']], [1, 2, 3, 4, 5])
        batches = request_batches(request(5), max_cues=2, max_chars=10000)
        self.assertEqual(batches[0]['read_only_context'][0]['id'], 3)
        self.assertEqual([r['id'] for r in batches[0]['segments']], [1, 2])

    def test_auto_holds_lock_during_provider_and_manual_runner_is_blocked(self):
        root = self.root / 'job'
        cfg = load_config(Path(__file__).resolve().parents[1] / 'config/example.json')
        cfg['_project_root'] = str(Path(__file__).resolve().parents[1])
        cfg['jobs_dir'] = str(self.root)
        video = self.root / 'source.mp4'; video.touch()
        marker = self.root / 'invoking'
        helper = self.root / 'provider.py'
        helper.write_text('import json,sys,time\nfrom pathlib import Path\n'
                          'Path(sys.argv[3]).write_text("invoking")\ntime.sleep(0.6)\n'
                          'req=json.load(open(sys.argv[1]))\n'
                          'json.dump({"schema":"aidub.translation_response.v1","job_id":"job","translator":{"kind":"command"},"segments":[{"id":1,"english":"Hello"}]},open(sys.argv[2],"w"))\n')
        spec = {'kind': 'command', 'command': [sys.executable, str(helper), '{request}', '{response}', str(marker)]}
        cfg['providers'] = {'translation': spec, 'repair': spec}
        job = Job.create(root, 'job', str(video), cfg)
        job.data['timeline'] = request()['segments']; job.save()
        write_json(root / 'inspect/probe.json', {'described': {'video': {'duration': 3}}})
        program = '''import sys
from pathlib import Path
from unittest.mock import patch
from aidub.job import Job
from aidub.unattended import run_unattended
job=Job(Path(sys.argv[1])); cfg=job.config()
def fake(job, **kwargs):
    fresh=Job(job.dir)
    if fresh.stage("translation")["status"]=="complete": return 3
    fresh.state="awaiting_translation"; fresh.save(); return 2
with patch("aidub.unattended.run_job", side_effect=fake), patch("aidub.unattended.require_synthesis_ready"):
    raise SystemExit(run_unattended(cfg,job.data["video"],"job"))
'''
        child = subprocess.Popen([sys.executable, '-c', program, str(root)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic() + 5
            while not marker.is_file() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(marker.is_file())
            with self.assertRaisesRegex(RuntimeError, 'locked'):
                run_job(Job(root))
            output, error = child.communicate(timeout=5)
            self.assertEqual(child.returncode, 3, output + error)
            with JobLock(root):
                pass
        finally:
            if child.poll() is None:
                child.kill(); child.wait()


class WorkerTests(unittest.TestCase):
    def test_stderr_beyond_pipe_capacity_and_shutdown(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); script = root / 'worker.py'; log = root / 'worker.log'
            script.write_text('import sys,json\nsys.stderr.write("diagnostic\\n"*20000);sys.stderr.flush()\n'
                              'print(json.dumps({"ready":True}),flush=True)\n'
                              'for line in sys.stdin:\n msg=json.loads(line)\n if msg["cmd"]=="shutdown":break\n print(json.dumps({"text":"Hello","language":"en"}),flush=True)\n')
            client = AsrClient(sys.executable, log_path=log, startup_timeout=2, worker_command=[sys.executable, str(script)])
            try:
                self.assertEqual(client.transcribe('unused')['text'], 'Hello')
                proc = client.proc
            finally:
                client.close()
            self.assertIsNotNone(proc.poll())
            self.assertGreater(log.stat().st_size, 100000)

    def test_startup_crash_diagnostic_is_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            client = AsrClient(sys.executable, log_path=Path(td) / 'worker.log', startup_timeout=2,
                               worker_command=[sys.executable, '-c', 'import sys; sys.stderr.write("specific startup failure");sys.exit(1)'])
            with self.assertRaisesRegex(RuntimeError, 'specific startup failure'):
                client.start()
            self.assertIsNone(client.proc)

    def test_library_chatter_is_redirected_away_from_json_protocol(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); model = root / 'weights.pt'; model.touch()
            (root / 'whisper.py').write_text('print("import chatter")\n'
                'def load_model(*a,**kw):\n print("load chatter")\n return Model()\n'
                'class Model:\n def transcribe(self,*a,**kw):\n  print("transcribe chatter")\n  return {"text":"Hello","language":"en"}\n')
            with patch.dict(os.environ, {'PYTHONPATH': str(root)}):
                client = AsrClient(sys.executable, model=str(model), device='cpu', log_path=root / 'worker.log', startup_timeout=3)
                try:
                    self.assertEqual(client.transcribe('unused')['text'], 'Hello')
                finally:
                    client.close()
            self.assertIn('transcribe chatter', (root / 'worker.log').read_text())


class VerificationIdentityTests(unittest.TestCase):
    def test_changed_checker_asr_settings_and_waveform_rerun_verification_only(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); cfg = load_config(); cfg['models'] = {'whisper_path': str(root / 'weights.pt')}
            Path(cfg['models']['whisper_path']).write_bytes(b'weights')
            t = np.arange(16000) / 16000
            audio = (0.2 * np.sin(2 * np.pi * 130 * t)).astype('float32')
            wav = root / 'line.wav'; sf.write(wav, audio, 16000, subtype='FLOAT')
            job = Job.create(root / 'job', 'j', 'source.mp4', cfg)
            meta = {'path': str(wav), 'seed': 43, 'cache_key': 'synthesis-key'}
            profile = speaker_profile(audio, 16000)
            with patch('aidub.verification._whisper_version', return_value='test-version'), \
                 patch.object(_LineAssessor, '_transcribe', return_value={'text': 'Hello there friend', 'language': 'en'}) as transcribe:
                assessor = _LineAssessor(job, cfg, profile, 'reference')
                assessor(meta, 'Hello there friend'); assessor(meta, 'Hello there friend')
                self.assertEqual(transcribe.call_count, 1)
                before_synth = synth_cache_key('Hello there friend', 'reference', 'ref', 43, cfg['qwen3'])
                for field, value in [('asr_language', 'English'), ('checker', 'changed-version')]:
                    cfg['quality'][field] = value
                    _LineAssessor(job, cfg, profile, 'reference')(meta, 'Hello there friend')
                cfg['whisper']['model'] = 'changed-model'
                _LineAssessor(job, cfg, profile, 'reference')(meta, 'Hello there friend')
                sf.write(wav, audio * 0.9, 16000, subtype='FLOAT')
                _LineAssessor(job, cfg, profile, 'reference')(meta, 'Hello there friend')
                self.assertEqual(transcribe.call_count, 5)
                self.assertEqual(before_synth, synth_cache_key('Hello there friend', 'reference', 'ref', 43, cfg['qwen3']))
            self.assertFalse(checkpoint_matches({'english':'Hello','reference_sha256':'reference'}, 'Hello', 'reference', verification_identity='new'))


class StreamingTests(unittest.TestCase):
    def fixture(self, root, bed, voice, sr=48000):
        sf.write(root / 'game.wav', bed, sr, subtype='FLOAT')
        sf.write(root / 'cue.wav', voice, sr, subtype='FLOAT')
        item = {'id':1,'start':0.1,'end':0.2,'placement_start':0.1,'placed':True,'used_path':str(root / 'cue.wav'),
                'status':'fit_unchanged','timing_error':''}
        return [item], alignment_meta(len(bed), sr, 0, 0, len(bed) / sr)

    def test_block_mix_matches_previous_placement_on_short_clip(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); sr=48000
            rng=np.random.default_rng(4)
            bed=rng.uniform(-0.1,0.1,(sr,2)).astype('float32')
            voice=rng.uniform(-0.2,0.2,5000).astype('float32')
            scheduled,meta=self.fixture(root,bed,voice)
            previous,_=place_voice(copy.deepcopy(scheduled),sr,sr,5)
            cfg={'mix':{'limiter':0.99},'processing':{'block_frames':257}}
            stream_mix(root/'game.wav',scheduled,root/'out',sr,meta,cfg,fade_ms=5)
            actual,rate=sf.read(root/'out/english_voice.wav',dtype='float32')
            mixed,_=sf.read(root/'out/english_mix.wav',dtype='float32')
            np.testing.assert_allclose(actual,previous,atol=1e-7)
            np.testing.assert_allclose(mixed,bed+previous[:,None],atol=1e-7)
            self.assertTrue(validate_audio_files(root/'game.wav',root/'out/english_voice.wav',root/'out/english_mix.wav',sr,meta,cfg)['shape_ok'])

    def test_peak_control_changes_only_voice_and_insufficient_headroom_is_explicit(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); sr=48000
            bed=np.full((sr,2),0.8,dtype='float32'); voice=np.full(5000,0.4,dtype='float32')
            scheduled,meta=self.fixture(root,bed,voice)
            cfg={'mix':{'limiter':0.99},'processing':{'block_frames':1024}}
            info=stream_mix(root/'game.wav',scheduled,root/'out',sr,meta,cfg)
            actual,_=sf.read(root/'out/english_voice.wav',dtype='float32')
            mixed,_=sf.read(root/'out/english_mix.wav',dtype='float32')
            self.assertGreater(info['sum_peak_before_gain'],1)
            self.assertLess(info['voice_gains']['1'],1)
            self.assertEqual(info['game_gain'],1)
            np.testing.assert_allclose(mixed-actual[:,None],bed,atol=1e-7)
            self.assertLessEqual(info['mix_peak'],0.990001)
            bed[:]=0.995
            scheduled,meta=self.fixture(root,bed,voice)
            info=stream_mix(root/'game.wav',scheduled,root/'out',sr,meta,cfg)
            self.assertFalse(info['source_headroom_ok'])
            self.assertFalse(scheduled[0]['placed'])
            self.assertEqual(scheduled[0]['timing_error'],'insufficient_game_headroom')
            np.testing.assert_allclose(sf.read(root/'out/english_mix.wav',dtype='float32')[0],bed,atol=1e-7)

    def test_recording_heap_memory_does_not_scale_with_duration(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); sr=1000; n=600000
            with sf.SoundFile(root/'game.wav','w',samplerate=sr,channels=2,subtype='PCM_16') as out:
                for _ in range(n//1000): out.write(np.zeros((1000,2),dtype='float32'))
            meta=alignment_meta(n,sr,0,0,n/sr)
            cfg={'mix':{'limiter':0.99},'processing':{'block_frames':4096}}
            tracemalloc.start()
            with patch('aidub.streaming.read_audio',side_effect=AssertionError('full audio read')):
                stream_mix(root/'game.wav',[],root/'out',sr,meta,cfg)
            _,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
            self.assertLess(peak,3*1024*1024)

    def test_energy_index_matches_original_convolution_and_segments_across_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); sr=1000; rng=np.random.default_rng(3)
            wav=rng.normal(0,0.01,(12000,1)).astype('float32');wav[3000:7000]=0
            mono=wav[:,0];window=10
            old=np.convolve(mono*mono,np.ones(window)/window,mode='same')>0.005**2
            index=EnergyIndex.build(lambda s,n: mono[s:s+n],len(mono),sr,0.005,0.01,257,root/'energy.sqlite')
            recovered=np.zeros(len(mono),dtype=bool)
            for lo,hi in index.runs():recovered[lo:hi]=True
            index.close(); np.testing.assert_array_equal(recovered,old)
            cfg=load_config()['segmentation'];sf.write(root/'mic.wav',wav,sr,subtype='FLOAT')
            doc={'segments':[{'start':0.2,'end':1,'text':'Hola'}, {'start':3.5,'end':4,'text':'silencio'}, {'start':7.4,'end':8,'text':'Puerta'}]}
            self.assertEqual(build_segments(doc,wav,sr,cfg),build_segments_file(doc,root/'mic.wav',cfg,block_frames=257))

    def test_source_chunks_resume_and_overlap_words_have_one_owner(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);cfg=load_config();cfg['models']={'whisper_path':str(root/'weights.pt')};(root/'weights.pt').touch()
            cfg['transcription']={'chunk_sec':5,'overlap_sec':1};cfg['processing']={'block_frames':256}
            job=Job.create(root/'job','j','unused',cfg);(job.dir/'extract').mkdir();sf.write(job.dir/'extract/mic_raw.wav',np.zeros((12000,1)),1000)
            calls=[]
            class FakeClient:
                def __init__(self,*a,**kw):pass
                def transcribe(self,path,**kw):
                    calls.append(path)
                    if len(calls)==2:raise KeyboardInterrupt
                    return {'segments':[{'start':1,'end':2,'text':'Hola','words':[{'word':'Hola','start':1.,'end':2.}]}]}
                def close(self):pass
            with self.assertRaises(KeyboardInterrupt):transcribe_chunks(job,cfg,{'mic_sha256':'mic'},client_factory=FakeClient)
            result=transcribe_chunks(job,cfg,{'mic_sha256':'mic'},client_factory=FakeClient)
            self.assertEqual(len(calls),4) # first complete chunk was skipped on resume
            self.assertEqual(read_json(job.dir/'transcribe/chunk_stats.json')['cache_hits'],1)
            shared={'segments':[{'start':4,'end':6,'words':[{'word':'one','start':4.,'end':4.8},{'word':'two','start':5.,'end':5.8}]}]}
            a=owned_segments(shared,0,0,5);b=owned_segments(shared,0,5,10)
            self.assertEqual([w['word'] for row in a+b for w in row['words']],['one','two'])


class MediaTests(unittest.TestCase):
    def test_missing_duration_and_nonzero_video_timestamps(self):
        doc={'streams':[{'codec_type':'video','index':0,'codec_name':'h264','start_time':'10','avg_frame_rate':'30/1'}],
             'format':{'duration':'99','start_time':'0'},'_aidub_video_timing':{'start':10,'end':12,'approximate':False}}
        video=describe_streams(doc)['video'];self.assertEqual(video['duration'],2);self.assertFalse(video['duration_approximate'])
        doc.pop('_aidub_video_timing');video=describe_streams(doc)['video']
        self.assertEqual(video['duration_source'],'container_fallback');self.assertTrue(video['duration_approximate'])
        self.assertIsNone(frame_check({'nb_frames':None},{'nb_frames':60})['ok'])

    def test_packet_probe_uses_max_presentation_endpoint_with_b_frames(self):
        def fake_run(cmd,stdout,**kwargs):
            stdout.write(b'pts_time=10|duration_time=0.1\npts_time=10.2|duration_time=0.1\npts_time=10.1|duration_time=0.1\n')
            return subprocess.CompletedProcess(cmd,0,stderr=b'')
        with patch('aidub.media.subprocess.run',side_effect=fake_run):
            span=video_packet_span('ffprobe','source')
        self.assertAlmostEqual(span['end']-span['start'],0.3)
        self.assertFalse(span['approximate'])

    def test_incompatible_copy_is_rejected_before_processing(self):
        doc={'video':{'codec_name':'vp8'},'audios':[{'audio_ordinal':0,'codec_name':'vorbis'}]}
        with self.assertRaisesRegex(RuntimeError,'re-encoding is refused'):validate_container(doc,0,'mp4')
        validate_container(doc,0,'mkv')

    def test_fresh_mkv_media_path_preserves_bitstream_and_bed(self):
        import shutil
        if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):self.skipTest('FFmpeg unavailable')
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);source=root/'source.mkv'
            cmd=['ffmpeg','-v','error','-y','-f','lavfi','-i','color=black:s=64x64:r=30:d=2',
                 '-f','lavfi','-i','sine=frequency=220:sample_rate=48000:duration=2',
                 '-map','0:v','-map','1:a','-map','1:a','-map','1:a','-c:v','libx264','-c:a','pcm_s16le','-ac','2',
                 '-output_ts_offset','5',str(source)]
            subprocess.run(cmd,check=True,capture_output=True,timeout=30)
            cfg=load_config();cfg['export']={'container':'mkv'};cfg['reference']['wav']=str(root/'ref.wav');sf.write(root/'ref.wav',np.zeros(1000),48000)
            cfg['processing']={'block_frames':1024};job=Job.create(root/'job','job',str(source),cfg)
            inspected=stage_inspect(job,cfg);self.assertEqual(inspected['described']['video']['start_time'],5)
            self.assertIsNone(inspected['described']['video']['nb_frames'])
            stage_extract(job,cfg,inspected)
            write_json(job.dir/'transcribe/corrections.json', {'untranscribed_energy': [], 'dropped': []})
            cue=root/'cue.wav';sf.write(cue,np.full(4800,0.1,dtype='float32'),48000,subtype='FLOAT')
            row={'id':1,'spanish':'Hola','english':'Hello','start':0.5,'end':0.7,'placed':True,'placement_start':0.5,'placement_end':0.6,
                 'used_path':str(cue),'tempo':1.,'status':'fit_unchanged','timing_error':'','quality':{'ok':True,'asr_text':'Hello'},'edge_ok':True}
            summary={'source_duration_sec':inspected['described']['video']['duration'],'segments':[row],'needs_repair':[],
                     'voice_presentation':True,'n_synth_fresh':0,'n_synth_cache_hits':1}
            job.data['timeline']=[row];job.stage('schedule').update(status='complete',fingerprint='schedule');job.save()
            gain=stage_mix(job,cfg,summary);report=stage_validate(job,cfg,summary,gain)
            self.assertEqual(report['status'],'complete',report['checks'])
            checks={r['name']:r for r in report['checks']}
            self.assertIsNone(checks['english_video_frames']['ok'])
            self.assertTrue(checks['video_bitstream_preserved']['ok']);self.assertTrue(checks['game_bed_continuous']['ok'])


class PortableStartupTests(unittest.TestCase):
    def test_explicit_config_overrides_invalid_default_before_interpreter_resolution(self):
        import shutil
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'bin').mkdir();(root/'config').mkdir();(root/'aidub').mkdir()
            shutil.copy2(Path(__file__).resolve().parents[1]/'bin/aidub',root/'bin/aidub')
            write_json(root/'config/default.json',{'executables':{'python_qwen':'/missing/santiago/python'}})
            explicit=root/'custom.json';write_json(explicit,{'executables':{'python_qwen':sys.executable}})
            (root/'aidub/__init__.py').touch()
            (root/'aidub/__main__.py').write_text('import os;print(os.environ["AIDUB_CONFIG"])')
            proc=subprocess.run([str(root/'bin/aidub'),'--config',str(explicit),'--help'],capture_output=True,text=True,timeout=5)
            self.assertEqual(proc.returncode,0,proc.stderr);self.assertIn(str(explicit),proc.stdout)

    def test_missing_weights_do_not_fall_back_to_download(self):
        from aidub.config import whisper_model_file
        from aidub.synth import resolve_local_snapshot
        with tempfile.TemporaryDirectory() as td:
            cfg=load_config();cfg['models']={'whisper_path':str(Path(td)/'missing.pt')}
            with self.assertRaisesRegex(RuntimeError,'will not download'):whisper_model_file(cfg)
            with patch('huggingface_hub.snapshot_download',side_effect=RuntimeError('not cached')) as download:
                with self.assertRaisesRegex(RuntimeError,'downloads are disabled'):resolve_local_snapshot('missing/model')
                self.assertTrue(download.call_args.kwargs['local_files_only'])


class FakeEndToEndTests(unittest.TestCase):
    def test_full_auto_repair_and_resume_use_fake_models_and_provider(self):
        from aidub.audio import metrics
        from aidub.unattended import run_unattended
        import shutil
        if not shutil.which('ffmpeg'):self.skipTest('FFmpeg unavailable')
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);sr=48000;t=np.arange(2*sr)/sr
            bed=np.stack([0.02*np.sin(2*np.pi*220*t)]*2,axis=1).astype('float32')
            mic=np.zeros_like(bed)
            for lo,hi in [(int(.2*sr),int(.5*sr)),(sr,int(1.3*sr))]:
                mic[lo:hi]=np.stack([.2*np.sin(2*np.pi*130*t[lo:hi])]*2,axis=1)
            for name,audio in [('mixed',bed+mic),('game',bed),('mic',mic)]:sf.write(root/(name+'.wav'),audio,sr)
            source=root/'source.mkv'
            subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','color=black:s=64x64:r=30:d=2',
                '-i',str(root/'mixed.wav'),'-i',str(root/'game.wav'),'-i',str(root/'mic.wav'),
                '-map','0:v','-map','1:a','-map','2:a','-map','3:a','-c:v','libx264','-c:a','pcm_s16le',str(source)],check=True,capture_output=True,timeout=30)
            cfg=load_config();cfg['jobs_dir']=str(root/'jobs');cfg['export']={'container':'mkv'}
            cfg['models']={'whisper_path':str(root/'weights.pt')};(root/'weights.pt').touch()
            cfg['reference']['wav']=str(root/'reference.wav');sf.write(root/'reference.wav',.1*np.sin(2*np.pi*130*t),sr)
            helper=root/'provider.py';calls=root/'provider_calls'
            helper.write_text('import json,sys\nfrom pathlib import Path\nreq=json.load(open(sys.argv[1]));role=sys.argv[3]\n'
                'with open(sys.argv[4],"a") as log:log.write(role+"\\n")\n'
                'rows=[dict(id=s["id"],english=("Hi" if role=="repair" else "Hello there"),**({"action":"revise","reason":"compact faithful wording"} if role=="repair" else {})) for s in req["segments"]]\n'
                'json.dump({"schema":"aidub."+role+"_response.v1","job_id":req["job_id"],"translator":{"kind":"command"},"segments":rows},open(sys.argv[2],"w"))\n')
            spec={'kind':'command','command':[sys.executable,str(helper),'{request}','{response}','{role}',str(calls)]}
            cfg['providers']={'translation':spec,'repair':spec};cfg['batching']={'max_cues':1,'max_chars':10000}
            cfg['processing']={'block_frames':1024}
            synth_calls=[];loads=[]
            class FakeBackend:
                def synthesize(self,text,reference_audio,reference_text,path,seed):
                    synth_calls.append((text,seed));duration=.2 if text=='Hi' else 1.2
                    signal=np.zeros(int((duration+.04)*sr),dtype='float32')
                    signal[int(.02*sr):-int(.02*sr)]=.1*np.sin(2*np.pi*130*np.arange(int(duration*sr))/sr)
                    Path(path).parent.mkdir(parents=True,exist_ok=True)
                    sf.write(path,signal,sr,subtype='FLOAT')
                    return dict(path=path,text=text,seed=seed,sample_rate=sr,duration_sec=len(signal)/sr,cache_hit=False,**metrics(signal))
            backend=FakeBackend()
            def get_backend(cfg):
                if not loads:loads.append(1)
                return backend
            class FakeClient:
                def __init__(self,*a,**kw):pass
                def transcribe(self,path,**kw):
                    if kw.get('full_result'):
                        return {'segments':[{'start':.2,'end':.5,'text':'Hola','words':[{'word':'Hola','start':.2,'end':.5,'probability':.9}]},
                                            {'start':1.,'end':1.3,'text':'Amigo','words':[{'word':'Amigo','start':1.,'end':1.3,'probability':.9}]}]}
                    return {'text':read_json(Path(path).with_suffix('.json'))['text'],'language':'en'}
                def start(self):pass
                def close(self):pass
            with patch('aidub.cli.preflight'),patch('aidub.unattended.require_synthesis_ready'),patch('aidub.transcription.AsrClient',FakeClient), \
                 patch('aidub.pipeline._LineAssessor._transcribe',lambda assessor,path: {'text':read_json(Path(path).with_suffix('.json'))['text'],'language':'en'}), \
                 patch('aidub.verification._whisper_version',return_value='fake'), \
                 patch('aidub.pipeline.get_shared_backend',side_effect=get_backend), \
                 patch('aidub.pipeline.shared_backend_loaded',side_effect=lambda:bool(loads)):
                self.assertEqual(run_unattended(cfg,str(source),'fresh'),0)
                paid_before=calls.read_text();synth_before=len(synth_calls)
                self.assertIn('repair',paid_before)
                with patch('aidub.pipeline.decode_ok',side_effect=AssertionError('validation should be cached')):
                    self.assertEqual(run_unattended(cfg,str(source),'fresh'),0)
                self.assertEqual(calls.read_text(),paid_before);self.assertEqual(len(synth_calls),synth_before)
                self.assertEqual(len(loads),1)
            report=read_json(root/'jobs/fresh/report/validation.json')
            self.assertEqual(report['n_placed'],2);self.assertEqual(report['n_unplaced'],0)
            self.assertTrue((root/'jobs/fresh/report/stage_metrics.jsonl').is_file())
            self.assertEqual(report['provider_totals']['uncertain_outcomes'],0)


class AdditionalRegressionTests(unittest.TestCase):
    def test_interrupted_job_records_resumable_failure(self):
        with tempfile.TemporaryDirectory() as td:
            job = Job.create(Path(td) / 'job', 'interrupted', '/unopened-source.mkv', load_config())
            with patch('aidub.pipeline.require_schedule_defaults'), \
                 patch('aidub.pipeline.stage_call', side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    run_job(job)
            saved = Job(job.dir)
            self.assertEqual(saved.state, 'failed')
            self.assertIn('checkpoints are retained', saved.error)
            with JobLock(job.dir):
                pass

    def test_worker_stdout_flood_reader_can_be_shut_down(self):
        script = 'import json,time; print(json.dumps({"ready":True}),flush=True); print("{}\\n"*400,flush=True); time.sleep(60)'
        client = AsrClient(sys.executable, startup_timeout=5,
                           worker_command=[sys.executable, '-u', '-c', script])
        client.start()
        time.sleep(.05)
        reader = client._reader
        client.close(force=True)
        self.assertFalse(reader.is_alive())

    def test_worker_interrupted_shutdown_reaps_child_and_closes_logs(self):
        from unittest.mock import Mock
        client = AsrClient(sys.executable)
        proc = Mock()
        proc.poll.return_value = None
        proc.wait.side_effect = [KeyboardInterrupt(), 0]
        client.proc = proc
        client._stderr = tempfile.TemporaryFile()
        handle = client._stderr
        with self.assertRaises(KeyboardInterrupt):
            client.close()
        proc.kill.assert_called_once()
        self.assertIsNone(client.proc)
        self.assertTrue(handle.closed)

    def test_missing_start_time_sentinel_uses_packet_timing(self):
        doc = {'streams': [{'index': 0, 'codec_type': 'video', 'codec_name': 'h264',
                            'start_time': 'N/A', 'duration': 'N/A'},
                           {'index': 1, 'codec_type': 'audio', 'start_time': 'N/A'}],
               '_aidub_video_timing': {'start': 5.0, 'end': 7.0, 'approximate': False}}
        described = describe_streams(doc)
        self.assertEqual(described['video']['start_time'], 5.0)
        self.assertEqual(described['video']['duration'], 2.0)
        self.assertEqual(described['audios'][0]['start_time'], 0.0)

    def test_measurement_wrapper_preserves_exit_and_reports_resource_scope(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / 'resources.json'
            script = Path(__file__).resolve().parents[1] / 'scripts/run-measured.py'
            proc = subprocess.run([sys.executable, str(script), str(output), sys.executable,
                                   '-c', 'raise SystemExit(3)'], timeout=10)
            self.assertEqual(proc.returncode, 3)
            report = read_json(output)
            self.assertEqual(report['exit_code'], 3)
            self.assertGreater(report['wall_seconds'], 0)
            self.assertGreater(report['exited_child_peak_ram_bytes'], 0)
            self.assertIn('not aggregate', report['memory_scope'])

    def test_worker_request_timeout_reaps_the_worker_promptly(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);script=root/'hang.py'
            script.write_text('import json,time,sys\nprint(json.dumps({"ready":True}),flush=True)\nfor line in sys.stdin:time.sleep(30)\n')
            client=AsrClient(sys.executable,log_path=root/'worker.log',startup_timeout=2,request_timeout=.05,
                             worker_command=[sys.executable,str(script)])
            started=time.monotonic()
            with self.assertRaisesRegex(RuntimeError,'timed out'):client.transcribe('unused')
            self.assertLess(time.monotonic()-started,3);self.assertIsNone(client.proc)

    def test_openai_retry_receives_feedback_without_a_network_call(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);req=root/'request.json';write_json(req,request());seen=[]
            class Reply:
                def __init__(self,data):self.data=data
                def __enter__(self):return self
                def __exit__(self,*args):pass
                def read(self,*args):return json.dumps(self.data).encode()
            def fake_urlopen(req,**kwargs):
                payload=json.loads(req.data);seen.append(payload['messages'][1]['content'])
                data=response(request())
                if len(seen)==1:data['segments']=[]
                return Reply({'choices':[{'message':{'content':json.dumps(data)}}]})
            spec={'kind':'openai_compatible','base_url':'https://example.invalid/v1','model':'test', 'api_key_env':'AIDUB_FAKE_TEST_KEY'}
            with patch.dict(os.environ,{'AIDUB_FAKE_TEST_KEY':'test-only-placeholder'}),patch('aidub.providers.urllib.request.urlopen',side_effect=fake_urlopen):
                invoke_checked(spec,req,root/'response.json','translation')
            self.assertEqual(len(seen),2);self.assertIn('validation_feedback',seen[1])

    def test_qa_model_change_does_not_change_source_window_identity(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);cfg=load_config();cfg['models']={'whisper_path':str(root/'source.pt')};(root/'source.pt').write_bytes(b'source')
            cfg['transcription']={'chunk_sec':5,'overlap_sec':1};job=Job.create(root/'job','j','unused',cfg)
            (job.dir/'extract').mkdir();sf.write(job.dir/'extract/mic_raw.wav',np.zeros((1000,1)),1000)
            calls=[]
            class Fake:
                def __init__(self,*a,**kw):pass
                def transcribe(self,*a,**kw):calls.append(1);return {'segments':[]}
                def close(self):pass
            transcribe_chunks(job,cfg,{'mic_sha256':'mic'},client_factory=Fake)
            with patch('aidub.verification._whisper_version',return_value='fake'):
                old=verification_identity(cfg,'ref')
                cfg['quality']['asr_model']='separate-verification-model'
                cfg['quality']['asr_model_path']=str(root/'verification.pt');(root/'verification.pt').write_bytes(b'verification')
                self.assertNotEqual(old,verification_identity(cfg,'ref'))
            transcribe_chunks(job,cfg,{'mic_sha256':'mic'},client_factory=Fake)
            self.assertEqual(len(calls),1)

    def test_tempo_provenance_survives_a_leading_shift(self):
        from aidub.pipeline import _attempt_from_audio,_apply_presentation
        from aidub.linework import leading_shift
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);cfg=load_config();sr=48000
            wav=root/'raw.wav';signal=np.zeros(int(1.14*sr),dtype='float32');signal[480:-480]=.1
            sf.write(wav,signal,sr,subtype='FLOAT');job=Job.create(root/'job','j','unused',cfg)
            seg={'id':1,'start':.5,'end':1.0}
            def tempo(ffmpeg,src,dest,factor,**kwargs):
                shortened=np.zeros(int(1.05*sr),dtype='float32');shortened[480:-480]=.1
                Path(dest).parent.mkdir(parents=True,exist_ok=True);sf.write(dest,shortened,sr,subtype='FLOAT')
            # A slightly shorter original trim requires legal tempo; ffmpeg still overruns the safe window.
            signal=np.zeros(int(1.1*sr),dtype='float32');signal[480:-480]=.1;sf.write(wav,signal,sr,subtype='FLOAT')
            meta={'path':str(wav),'duration_sec':1.1}
            with patch('aidub.pipeline.atempo',side_effect=tempo):
                chosen=_attempt_from_audio(job,cfg,seg,'Hello',43,'primary',meta,0,1.5,2)
            self.assertFalse(chosen['placed']);self.assertGreater(chosen['tempo'],1)
            shift=leading_shift(.5,chosen['generated_duration_sec'],0,1.5,.4)
            self.assertGreater(shift,.02)
            chosen.update(placed=True,placement_start=.5-shift,status='spill_into_leading_silence')
            presented=_apply_presentation(job,cfg,seg,chosen,0,1.5,2,None)
            self.assertEqual(sf.info(presented['used_path']).frames,int(1.05*sr))

    def test_provider_interruption_reaps_its_own_process_group(self):
        from aidub.providers import _run_command
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);req=root/'request.json';write_json(req,request())
            with patch('aidub.providers.subprocess.Popen') as popen,patch('aidub.providers.os.killpg') as kill:
                proc=popen.return_value;proc.pid=12345;proc.wait.side_effect=[KeyboardInterrupt,0]
                with self.assertRaises(KeyboardInterrupt):_run_command({'command':['fake']},req,root/'response.json','translation')
                kill.assert_called_once()


class PreflightAndLegacyTests(unittest.TestCase):
    def test_failed_paid_call_preflight_does_not_spend_an_attempt(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);req=root/'request.json';write_json(req,request())
            with patch('aidub.providers.invoke_provider',side_effect=AssertionError('no external invocation')):
                with self.assertRaisesRegex(ProviderError,'no provider attempt was started'):
                    invoke_checked({'kind':'command','command':[sys.executable]},req,root/'response.json','translation',
                                   before_invoke=lambda: (_ for _ in ()).throw(RuntimeError('missing model')))
            state=read_json(next(root.glob('response_attempts/*/state.json')))
            self.assertEqual(state['attempts'],[])

    def test_incomplete_sharded_snapshot_is_rejected_offline(self):
        from aidub.config import qwen_snapshot
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);write_json(root/'config.json',{});write_json(root/'model.safetensors.index.json',{'weight_map':{'a':'part1.safetensors','b':'part2.safetensors'}})
            (root/'part1.safetensors').write_bytes(b'one')
            cfg=load_config();cfg['models']={'qwen_path':str(root)}
            with self.assertRaisesRegex(RuntimeError,'Incomplete Qwen snapshot'):qwen_snapshot(cfg)

    def test_legacy_transcript_ids_survive_quality_only_migration(self):
        from aidub.pipeline import stage_transcribe
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);cfg=load_config();cfg.pop('transcription',None)
            cfg['models']={'whisper_path':str(root/'weights.pt')};(root/'weights.pt').write_bytes(b'weights')
            alignment={'mic_sha256':'mic','offset_sec':0.}
            job=Job.create(root/'job','j','unused',cfg)
            legacy=fingerprint({'mic':'mic','offset':0.,'whisper':cfg['whisper'],'segmentation':cfg['segmentation']})
            job.data['timeline']=[{'id':42,'spanish':'Hola','english':'Hello','start':.1,'end':.3}]
            for name in ['raw','segments','corrections']:write_json(job.dir/f'transcribe/{name}.json',{'segments':job.data['timeline']})
            write_json(job.dir/'timeline.json',{'segments':job.data['timeline']})
            job.set_stage('transcribe','complete',legacy)
            cfg['quality']['checker']='new-checker'
            with patch('aidub.pipeline.transcribe_chunks',side_effect=AssertionError('do not retranscribe')):
                result=stage_transcribe(job,cfg,alignment)
            self.assertEqual(result['segments'][0]['id'],42);self.assertEqual(result['segments'][0]['english'],'Hello')


if __name__=='__main__':unittest.main()
