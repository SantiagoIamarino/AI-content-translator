"""Optional-output dependencies and one tiny media fixture; no AI execution."""
import copy
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf

from aidub.config import load_config, new_job_config, spanish_comparison_enabled
from aidub.export import picture_source, preview_cmd
from aidub.job import Job
from aidub.media import validate_container
from aidub.pipeline import stage_inspect, stage_extract, stage_mix, stage_validate
from aidub.risk import build_risk_report, risk_fingerprint
from aidub.storage import storage_budget
from aidub.util import read_json, write_json, sha256_file


class ComparisonConfigurationTests(unittest.TestCase):
    def test_new_defaults_explicit_opt_in_and_legacy_snapshot(self):
        self.assertFalse(spanish_comparison_enabled(load_config()))
        legacy = {'export': {'container': 'mp4'}}
        self.assertTrue(spanish_comparison_enabled(legacy))
        self.assertFalse(spanish_comparison_enabled(new_job_config(legacy)))
        self.assertNotIn('spanish_compare', legacy['export'])
        self.assertTrue(spanish_comparison_enabled(new_job_config({'export': {'spanish_compare': True}})))
        with tempfile.TemporaryDirectory() as td:
            job = Job.create(Path(td) / 'new', 'new', 'unused', legacy)
            self.assertIs(job.config()['export']['spanish_compare'], False)
            write_json(job.dir / 'config.json', legacy)  # Simulate an untouched pre-batch-4 snapshot.
            self.assertTrue(spanish_comparison_enabled(Job(job.dir).config()))
        for value in ('false', 0, None, []):
            with self.subTest(value=value), self.assertRaises(ValueError):
                spanish_comparison_enabled({'export': {'spanish_compare': value}})

    def test_storage_estimates_one_or_two_full_exports(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); source = root / 'source'; source.write_bytes(b'x' * 1234)
            job = root / 'job'; job.mkdir()
            cfg = load_config(); cfg['processing']['storage_reserve_bytes'] = 0
            described = {'video': {'duration': 2.}}
            mapping = {role: {'channels': 2} for role in ('mic', 'game')}
            off = storage_budget(job, source, described, mapping, cfg)
            cfg['export']['spanish_compare'] = True
            on = storage_budget(job, source, described, mapping, cfg)
            self.assertEqual(on['estimated_total_bytes'] - off['estimated_total_bytes'], source.stat().st_size)
            self.assertEqual((off['full_video_exports'], on['full_video_exports']), (1, 2))
            cfg['export']['spanish_compare'] = False
            (job / 'output').mkdir(); (job / 'output/spanish_compare.mp4').write_bytes(b'stale')
            retained = storage_budget(job, source, described, mapping, cfg)
            self.assertEqual(retained['estimated_additional_bytes'], off['estimated_additional_bytes'])
            self.assertEqual(retained['retained_unrequested_comparison_bytes'], 5)

    def test_mp4_video_protection_remains_when_mixed_audio_is_not_copied(self):
        doc = {'video': {'codec_name': 'h264'}, 'audios': [{'audio_ordinal': 0, 'codec_name': 'pcm_s16le'}]}
        validate_container(doc, 0, 'mp4', comparison=False)
        with self.assertRaises(RuntimeError): validate_container(doc, 0, 'mp4', comparison=True)
        doc['video']['codec_name'] = 'vp8'
        with self.assertRaises(RuntimeError): validate_container(doc, 0, 'mp4', comparison=False)

    def test_preview_maps_configured_audio_and_picture_origin(self):
        cmd = preview_cmd('ffmpeg', Path('source'), Path('preview'), .5, 1., audio_ordinal=1, video_start=5.)
        self.assertIn('0:a:1', cmd)
        self.assertEqual(cmd[cmd.index('-ss') + 1], '5.500000')
        self.assertEqual(cmd[cmd.index('-seek_timestamp') + 1], '1')

    def test_picture_only_evaluation_fallback_prefers_required_english_output(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); (root / 'output').mkdir()
            write_json(root / 'manifest.json', {'video': str(root / 'missing'), 'stages': {}})
            english = root / 'output/english_PARTIAL.mp4'; english.touch()
            spanish = root / 'output/spanish_compare.mp4'; spanish.touch()
            self.assertEqual(picture_source(root), english)
            english.unlink()
            self.assertEqual(picture_source(root), spanish)  # Historical picture only, never Spanish audio.
            spanish.unlink()
            with self.assertRaisesRegex(RuntimeError, 'saved copied picture'): picture_source(root)


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
class TinyComparisonMediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(); cls.root = Path(cls.temp.name)
        cls.source = cls.root / 'source.mkv'
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=size=64x64:rate=10:duration=2',
                        '-f', 'lavfi', '-i', 'sine=frequency=220:sample_rate=48000:duration=2',
                        '-f', 'lavfi', '-i', 'sine=frequency=660:sample_rate=48000:duration=2',
                        '-f', 'lavfi', '-i', 'sine=frequency=130:sample_rate=48000:duration=2',
                        '-map', '0:v', '-map', '1:a', '-map', '2:a', '-map', '3:a', '-c:v', 'libx264',
                        '-c:a', 'pcm_s16le', '-ac', '2', '-output_ts_offset', '5', str(cls.source)],
                       capture_output=True, check=True, timeout=30)

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def setUp(self):
        self.guards = []
        for target in ('aidub.providers.invoke_provider', 'aidub.pipeline.get_shared_backend',
                       'aidub.pipeline.synthesize_cached', 'aidub.pipeline.stage_transcribe'):
            p = patch(target, side_effect=AssertionError('No AI execution')); self.guards.append(p.start()); self.addCleanup(p.stop)

    def tearDown(self):
        for guard in self.guards: guard.assert_not_called()

    def job(self, enabled, suffix):
        cfg = load_config(); cfg['export'] = {'container': 'mkv', 'spanish_compare': enabled}
        cfg['audio_mapping'].update(mic_ordinal=2, game_ordinal=0, mixed_ordinal=1)
        cfg['processing']['block_frames'] = 1024
        cfg['reference']['wav'] = str(self.root / 'reference.wav')
        sf.write(cfg['reference']['wav'], np.zeros(1000), 48000)
        job = Job.create(self.root / (self._testMethodName + suffix), 'fixture', str(self.source), cfg)
        cfg = job.config(); inspected = stage_inspect(job, cfg); stage_extract(job, cfg, inspected)
        self.assertEqual(inspected['described']['video']['start_time'], 5.)
        write_json(job.dir / 'transcribe/corrections.json', {'untranscribed_energy': []})
        cue = job.dir / 'cue.wav'; sf.write(cue, .03 * np.sin(2 * np.pi * 130 * np.arange(4800) / 48000), 48000)
        row = {'id': 1, 'spanish': 'Hola.', 'english': 'Hello.', 'start': .5, 'end': .7, 'placed': True,
               'placement_start': .5, 'placement_end': .6, 'used_path': str(cue), 'tempo': 1., 'status': 'fit_unchanged',
               'timing_error': '', 'quality': {'ok': True, 'asr_text': 'Hello.', 'verification_complete': True}, 'edge_ok': True}
        summary = {'source_duration_sec': inspected['described']['video']['duration'], 'segments': [row], 'needs_repair': [],
                   'voice_presentation': True, 'n_synth_fresh': 0, 'n_synth_cache_hits': 0}
        job.data['timeline'] = [row]; job.stage('schedule').update(status='complete', fingerprint='fixture-schedule'); job.save()
        write_json(job.dir / 'timeline.json', {'segments': [row]})
        return job, cfg, summary

    def test_both_modes_preserve_english_gates_and_an_english_failure(self):
        results = []
        for enabled in (False, True):
            job, cfg, summary = self.job(enabled, str(enabled))
            gain = stage_mix(job, cfg, summary); report = stage_validate(job, cfg, summary, gain)
            self.assertEqual(report['status'], 'complete', report['checks'])
            self.assertEqual((job.dir / 'output/spanish_compare.mkv').exists(), enabled)
            self.assertEqual('spanish_compare' in report['outputs'], enabled)
            results.append({c['name']: (c['ok'], c['status'], c['required']) for c in report['checks'] if not c['name'].startswith('spanish_')})
            # The same real media fixture still fails an English protection in both modes.
            with patch('aidub.pipeline.decode_ok', side_effect=lambda ff, path, **kw: (False, 'injected English failure')
                       if Path(path).name.startswith('english') else (True, '')):
                job.stage('validate')['status'] = 'pending'; job.save()
                bad = stage_validate(job, cfg, summary, gain)
            self.assertEqual(bad['status'], 'failed')
        self.assertEqual(results[0], results[1])

    def test_toggle_and_missing_comparison_reuse_english_render(self):
        job, cfg, summary = self.job(False, '')
        gain = stage_mix(job, cfg, summary); english = Path(gain['english_video']); stamp = english.stat().st_mtime_ns
        with patch('aidub.pipeline.stream_mix', side_effect=AssertionError('no English remix')):
            cfg['export']['spanish_compare'] = True
            stage_mix(job, cfg, summary)
            dest = job.dir / 'output/spanish_compare.mkv'; self.assertTrue(dest.is_file())
            dest.unlink()
            with self.assertRaises(FileNotFoundError): stage_validate(job, cfg, summary, gain)
            stage_mix(job, cfg, summary); self.assertTrue(dest.is_file())
            cfg['export']['spanish_compare'] = False
            before = sha256_file(dest)
            with patch('aidub.pipeline.run_cmd', side_effect=AssertionError('no remux')):
                stage_mix(job, cfg, summary)
            self.assertEqual(sha256_file(dest), before)
        self.assertEqual(english.stat().st_mtime_ns, stamp)

    def test_legacy_comparison_is_adopted_without_remux(self):
        job, cfg, summary = self.job(True, '')
        gain = stage_mix(job, cfg, summary)
        (job.dir / 'mix/spanish_compare.json').unlink()
        cfg['export'].pop('spanish_compare')  # Legacy missing setting retains comparison-on.
        with patch('aidub.pipeline.run_cmd', side_effect=AssertionError('no remux')), \
             patch('aidub.pipeline.stream_mix', side_effect=AssertionError('no remix')):
            stage_mix(job, cfg, summary)
        self.assertTrue(read_json(job.dir / 'mix/spanish_compare.json')['adopted_legacy'])

    def test_comparison_off_can_export_english_mp4_from_pcm_source(self):
        job, cfg, summary = self.job(False, '')
        cfg['export']['container'] = 'mp4'
        stage_inspect(job, cfg)
        gain = stage_mix(job, cfg, summary); report = stage_validate(job, cfg, summary, gain)
        self.assertEqual(report['status'], 'complete', report['checks'])
        self.assertEqual(Path(report['english_video']).suffix, '.mp4')

    def test_stale_comparison_is_ignored_in_validation_and_preview_cache(self):
        job, cfg, summary = self.job(False, '')
        gain = stage_mix(job, cfg, summary); dest = job.dir / 'output/spanish_compare.mkv'
        dest.write_bytes(b'stale invalid media')
        report = stage_validate(job, cfg, summary, gain)
        self.assertEqual(report['status'], 'complete')
        self.assertTrue(all(c['status'] == 'not_requested' for c in report['checks'] if c['name'].startswith('spanish_')))
        before = risk_fingerprint(job.dir, cfg); dest.write_bytes(b'changed stale media')
        self.assertEqual(risk_fingerprint(job.dir, cfg), before)
        with patch('aidub.pipeline.decode_ok', side_effect=AssertionError('cached validation')):
            stage_validate(job, cfg, summary, gain)
        cfg['audio_mapping']['mixed_ordinal'] = 0
        self.assertNotEqual(risk_fingerprint(job.dir, cfg), before)

    def test_source_preview_works_without_full_comparison_and_uses_mixed_track(self):
        job, cfg, summary = self.job(False, '')
        gain = stage_mix(job, cfg, summary); stage_validate(job, cfg, summary, gain)
        # Give the line a listening risk without changing its English output.
        summary['segments'][0]['quality']['short_phrase_unverified'] = True
        write_json(job.dir / 'mix/placed_summary.json', summary)
        report = build_risk_report(job.dir, cfg, limit=1, previews=True)
        preview = Path(report['items'][0]['excerpts']['preview_es'])
        data = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(preview), '-vn', '-ac', '1', '-ar', '48000', '-f', 'f32le', '-'],
                              capture_output=True, check=True, timeout=20).stdout
        audio = np.frombuffer(data, dtype='<f4'); spectrum = np.abs(np.fft.rfft(audio))
        frequency = np.fft.rfftfreq(len(audio), 1 / 48000)[spectrum.argmax()]
        self.assertAlmostEqual(frequency, 660., delta=3.)
        self.assertFalse((job.dir / 'output/spanish_compare.mkv').exists())

    def test_bounded_preview_preserves_nonzero_picture_time_origin(self):
        dest = self.root / 'origin-preview.mp4'
        subprocess.run(preview_cmd('ffmpeg', self.source, dest, .5, .8, audio_ordinal=1, video_start=5.),
                       check=True, capture_output=True, timeout=30)
        def frame(source, absolute=None):
            cmd = ['ffmpeg', '-v', 'error']
            if absolute is not None: cmd += ['-seek_timestamp', '1', '-ss', str(absolute)]
            cmd += ['-i', str(source), '-frames:v', '1', '-vf', 'scale=64:64', '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-']
            return np.frombuffer(subprocess.run(cmd, capture_output=True, check=True, timeout=20).stdout, dtype=np.uint8).astype(float)
        actual = frame(dest); correct = frame(self.source, 5.5); wrong = frame(self.source, 5.)
        self.assertLess(np.abs(actual - correct).mean(), np.abs(actual - wrong).mean())


if __name__ == '__main__': unittest.main()
