#!/usr/bin/env python3
"""Replay saved, verified candidates without synthesis or providers.

Writes an explicitly experimental preview, never changes job status. Use this
checkout's configured Python. Source jobs and output are locked throughout.
"""
import argparse
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import soundfile as sf

from aidub.audio import read_audio, to_mono
from aidub.continuity import source_pacing_score
from aidub.export import mux_english_cmd
from aidub.job import JobLock
from aidub.media import run_cmd, bitstream_md5, encoded_audio_metrics
from aidub.pipeline import _attempt_from_audio, _present_v3
from aidub.selection import settings, pacing, score_take, running_profile, choose
from aidub.streaming import stream_mix, validate_audio_files
from aidub.util import read_json, write_json, sha256_file


def crop(src, dst, start, end):
    with sf.SoundFile(src) as source:
        source.seek(round(start*source.samplerate))
        # Evidence windows are bounded to <= five minutes.
        data=source.read(round((end-start)*source.samplerate),dtype='float32',always_2d=True)
        sf.write(dst,data,source.samplerate,subtype='FLOAT')


def run(job, out, start, end, recheck_saved_asr=False):
    cfg=read_json(job/'config.json')
    cfg.setdefault('voice_selection',{}).update(enabled=True, source_pacing={'enabled':True,'weight':4.0})
    edge=cfg['voice_edge']
    edge.update(presentation_version=3, protection={'floor_rms':.0015,'max_lead_ms':80,'max_tail_ms':400,'settle_ms':20})
    opts=settings(cfg)
    summary=read_json(job/'mix/placed_summary.json')
    source_duration=summary['source_duration_sec']
    end=min(end,source_duration)
    if not 0 <= start < end or end-start>300:
        raise ValueError('Choose an evidence window of at most 300 seconds')
    ffmpeg=cfg['executables']['ffmpeg']
    rows=summary['segments']
    selected=[s for s in rows if start <= s['start'] < end]
    if any(s.get('placed') and s['placement_start'] < start < s['placement_end'] for s in rows):
        raise ValueError('Choose a start outside a placed cue')
    if any(s.get('placed') and s['placement_end'] > end for s in selected):
        raise ValueError('Choose an end outside a placed cue')
    for name,src in [('mic',job/'extract/mic_raw.wav'),('game',job/'extract/game_raw.wav'),
                     ('before_voice',job/'output/english_voice.wav'),('before_mix',job/'output/english_mix.wav')]:
        crop(src,out/(name+'.wav'),start,end)
    offset=float(read_json(job/'extract/alignment.json').get('offset_sec',0))
    if abs(offset)>1e-6:
        raise ValueError('This evidence command requires zero aligned track offset')
    # Preserve picture from the original source or its existing copied comparison.
    source=Path(read_json(job/'manifest.json')['video'])
    using_copy=not source.is_file()
    if using_copy:
        source=job/'output/spanish_compare.mp4'
    run_cmd([ffmpeg,'-v','error','-y','-ss',str(start),'-i',str(source),'-t',str(end-start),
             '-map','0:v:0','-c:v','copy','-an',str(out/'picture.mp4')])
    audit=[]
    planned=[]
    fixed=[]
    occupied=start
    profiles=[(s.get('quality') or {}).get('speaker') or {} for s in rows if s['start']<start and s.get('placed')]
    jobview=SimpleNamespace(dir=out)
    for s in selected:
        nxt=min(next((float(r['start']) for r in rows if r['start']>s['start']),source_duration),end)
        candidates=[]
        record={'id':s['id'],'start':s['start'],'end':s['end'],'spanish':s['spanish'],'english':s['english'],
                'before_seed':s.get('seed'),'before_end':s.get('placement_end'),'candidates':[]}
        for a in s.get('attempts',[]):
            if a['text']!=s['english'] or (not recheck_saved_asr and not (a.get('quality') or {}).get('ok')):
                continue
            raw=Path(a['raw_path']);meta=read_json(raw.with_suffix('.json'))
            digest=sha256_file(raw)
            if digest!=meta.get('waveform_sha256'):
                raise ValueError(f'Raw waveform hash mismatch: {raw}')
            attempt=_attempt_from_audio(jobview,cfg,s,a['text'],a['seed'],a['kind'],dict(meta,path=str(raw)),occupied,nxt,end)
            quality = a['quality']
            if recheck_saved_asr:
                from aidub.quality import assess_candidate
                x, sr = read_audio(raw)
                quality = assess_candidate(to_mono(x), sr, a['text'], summary['reference_profile'],
                           asr_text=quality.get('asr_text'), asr_language=quality.get('asr_language'),
                           asr_skipped=quality.get('asr_skipped',False), text_checker='sequence-v1', pacing_opts=opts,
                           min_speaker_features=int(cfg['quality'].get('min_speaker_features',2)))
                quality['asr_mean_probability'] = a['quality'].get('asr_mean_probability')
                if not quality['ok']:
                    continue
            attempt['quality']=quality
            if attempt['placed']:
                attempt=_present_v3(jobview,cfg,s,attempt,occupied,nxt,end,s.get('presentation',{}).get('target_rms'),edge)
            x,sr=read_audio(raw)
            sel=score_take(attempt,pacing(to_mono(x),sr,a['text'],tempo=attempt['tempo']),summary['reference_profile'],running_profile(profiles),opts)
            attempt['selection']=source_pacing_score(sel,s,opts)
            record['candidates'].append({'seed':a['seed'],'raw_sha256':digest,'placed':attempt['placed'],
                                         'reason':attempt['timing_error'],'score':attempt['selection'],
                                         'edge':attempt.get('edge')})
            if a['seed']==s['seed']:
                # Exact raw-take comparison, separate from reselection.
                pair=out/f"cue_{s['id']:03d}";pair.mkdir(exist_ok=True)
                import shutil
                shutil.copy2(raw,pair/'raw.wav');shutil.copy2(s['used_path'],pair/'before.wav')
                if attempt['placed']:
                    shutil.copy2(attempt['used_path'],pair/'processed_same_take.wav')
                fixed.append({'id':s['id'],'seed':a['seed'],'processed':attempt['placed'],'reason':attempt['timing_error']})
            if attempt['placed']:
                candidates.append(attempt)
        if candidates:
            a=choose(candidates)
            row=copy.deepcopy(s)
            row.update(a)
            row['placement_end']=a['placement_start']+a['generated_duration_sec']
            occupied=row['placement_end']
            profiles.append(a['quality'].get('speaker') or {})
            record.update(after_seed=a['seed'],after_start=a['placement_start'],after_end=occupied)
            row['start']-=start;row['end']-=start;row['placement_start']-=start;row['placement_end']-=start
            planned.append(row)
        else:
            row=copy.deepcopy(s);row.update(placed=False,timing_error='no_cached_candidate_with_protected_ending')
            row['start']-=start;row['end']-=start
            planned.append(row);record['omitted']=row['timing_error']
        audit.append(record)
    sr=48000
    meta={'lead_samples':0,'tail_samples':0,'truncated_samples':0,'total_samples':round((end-start)*sr)}
    gains=stream_mix(out/'game.wav',planned,out,sr,meta,cfg,fade_ms=0)
    pcm=validate_audio_files(out/'game.wav',out/'english_voice.wav',out/'english_mix.wav',sr,meta,cfg)
    # Compare both versions using exactly the same copied video slice.
    for label,wav in [('before',out/'before_mix.wav'),('after_cached',out/'english_mix.wav')]:
        run_cmd(mux_english_cmd(ffmpeg,str(out/'picture.mp4'),str(wav),str(out/(label+'.mp4'))))
        run_cmd([ffmpeg,'-v','error','-i',str(out/(label+'.mp4')),'-f','null','-'])
    picture_hash=bitstream_md5(ffmpeg,str(out/'picture.mp4'))
    video_ok=all(bitstream_md5(ffmpeg,str(out/(name+'.mp4')))==picture_hash for name in ['before','after_cached'])
    encoded=encoded_audio_metrics(ffmpeg,str(out/'after_cached.mp4'))
    # Comparable waveforms: each row has identical time extent and scale.
    run_cmd([ffmpeg,'-v','error','-y','-i',str(out/'mic.wav'),'-i',str(out/'before_voice.wav'),'-i',str(out/'english_voice.wav'),
             '-filter_complex','[0:a]aformat=channel_layouts=mono,showwavespic=s=1600x180:colors=blue:scale=lin[a];'
             '[1:a]showwavespic=s=1600x180:colors=red:scale=lin[b];'
             '[2:a]showwavespic=s=1600x180:colors=green:scale=lin[c];[a][b][c]vstack=inputs=3[v]',
             '-map','[v]','-frames:v','1',str(out/'waveforms.png')])
    report={'status':'experimental_cached_replay_not_job_acceptance','job':str(job),'interval':[start,end],
            'rechecked_saved_asr':recheck_saved_asr,'new_translation_calls':0,'new_synthesis':0,'reference_sha256_at_generation':summary['reference_sha256'],
            'counts':{'retained':len(selected),'translated':sum(bool(s['english']) for s in selected),
                      'before_placed':sum(bool(s['placed']) for s in selected),
                      'after_placed':sum(bool(s['placed']) for s in planned),'omitted':sum(not s['placed'] for s in planned)},
            'pcm':pcm,'video_copy_bitstream_equal':video_ok,'encoded_audio':encoded,'gains':gains,
            'picture_source_is_saved_copy':using_copy,'fixed_take_comparisons':fixed,'cues':audit,
            'limitations':['No listening performed. Saved ASR checks reused after raw hash verification.',
                           'Video slice seeks to keyframes; audio excerpts have exact requested sample boundaries.',
                           'No source microphone passthrough. Energy is not a speech classification.']}
    write_json(out/'evidence.json',report)
    print(json.dumps({k:v for k,v in report.items() if k in ['counts','pcm','video_copy_bitstream_equal']},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--recheck-saved-asr',action='store_true',help='Re-evaluate the saved ASR text with current checker; no new hearing')
    parser.add_argument('--start',type=float,default=0)
    parser.add_argument('--end',type=float,required=True)
    args=parser.parse_args()
    job,out=args.job.resolve(),args.output.resolve()
    if out==job or job in out.parents:
        raise ValueError('Evidence output must be separate from the source job')
    with JobLock(job),JobLock(out):
        run(job,out,args.start,args.end,args.recheck_saved_asr)
