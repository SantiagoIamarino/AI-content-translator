"""One source ASR worker, bounded overlapping windows, independent checkpoints."""
from __future__ import annotations
import copy
import os
from pathlib import Path
import time
import soundfile as sf

from .asr_client import AsrClient, whisper_python
from .config import whisper_model_file
from .streaming import block_frames
from .util import fingerprint, read_json, write_json
from .verification import file_identity


def copy_audio_window(source: Path, dest: Path, lo: int, hi: int, n_block: int):
    tmp = dest.with_name(dest.stem + f".{os.getpid()}.tmp.wav")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with sf.SoundFile(source) as src, sf.SoundFile(tmp, 'w', samplerate=src.samplerate,
                                                channels=src.channels, subtype='PCM_16') as out:
        src.seek(lo)
        remaining = hi - lo
        while remaining:
            n = min(n_block, remaining)
            data = src.read(n, dtype='float32', always_2d=True)
            if len(data) != n:
                raise RuntimeError("Mic window extends past EOF")
            out.write(data)
            remaining -= n
    os.replace(tmp, dest)


def owned_segments(result, window_start, core_start, core_end):
    rows = []
    for segment in result.get('segments') or []:
        seg = copy.deepcopy(segment)
        words = seg.get('words') or []
        if words:
            words = [w for w in words if core_start <= window_start + (float(w['start']) + float(w['end'])) / 2 < core_end]
            if not words:
                continue
            for word in words:
                word['start'] += window_start
                word['end'] += window_start
            seg.update(words=words, text=' '.join(w['word'].strip() for w in words), start=words[0]['start'], end=words[-1]['end'])
        else:
            if not core_start <= window_start + (float(seg['start']) + float(seg['end'])) / 2 < core_end:
                continue
            seg['start'] += window_start
            seg['end'] += window_start
        rows.append(seg)
    return rows


def transcribe_chunks(job, cfg, alignment, *, client_factory=None):
    client_factory = client_factory or AsrClient
    mic = job.dir / 'extract/mic_raw.wav'
    info = sf.info(mic)
    settings = cfg.get('transcription') or {}
    seconds, overlap = float(settings.get('chunk_sec', 600)), float(settings.get('overlap_sec', 2))
    if not 5 <= seconds <= 1800 or not 0 <= overlap < seconds / 2:
        raise RuntimeError("transcription chunk_sec must be 5..1800 and overlap_sec below half a chunk")
    model = whisper_model_file(cfg)
    identity = fingerprint({'mic': alignment['mic_sha256'], 'whisper': cfg['whisper'],
                            'weights': file_identity(model), 'chunks': settings, 'version': 2})
    directory = job.dir / 'transcribe/chunks' / identity
    window = int(round(seconds * info.samplerate))
    pad = int(round(overlap * info.samplerate))
    budgets = cfg.get('timeouts') or {}
    client = None
    segments, hits, calls, seconds_total = [], 0, 0, 0.0
    try:
        for i, core in enumerate(range(0, info.frames, window)):
            end = min(info.frames, core + window)
            lo, hi = max(0, core - pad), min(info.frames, end + pad)
            result_path = directory / f'chunk_{i:04d}.json'
            key = fingerprint({'identity': identity, 'lo': lo, 'hi': hi, 'core': core, 'end': end})
            saved = read_json(result_path) if result_path.is_file() else {}
            if saved.get('identity') == key:
                result = saved['result']
                hits += 1
            else:
                audio_path = directory / f'chunk_{i:04d}.wav'
                copy_audio_window(mic, audio_path, lo, hi, block_frames(cfg))
                if client is None:
                    client = client_factory(whisper_python(cfg['executables']['whisper']), model=str(model),
                                            device=cfg['whisper']['device'], log_path=job.dir / 'transcribe/whisper.log',
                                            startup_timeout=float(budgets.get('worker_startup_sec', 180)),
                                            request_timeout=float(budgets.get('asr_chunk_sec', 1800)))
                started = time.perf_counter()
                result = client.transcribe(str(audio_path), language=cfg['whisper']['language'], word_timestamps=True,
                                           full_result=True, options=cfg['whisper'].get('decode_options'))
                runtime = time.perf_counter() - started
                seconds_total += runtime
                calls += 1
                write_json(result_path, {'identity': key, 'result': result, 'wall_seconds': runtime})
            segments.extend(owned_segments(result, lo / info.samplerate, core / info.samplerate, end / info.samplerate))
        segments.sort(key=lambda row: (row['start'], row['end']))
        write_json(job.dir / 'transcribe/chunk_stats.json', {'new_calls': calls, 'cache_hits': hits,
                   'worker_loads': int(client is not None), 'wall_seconds': seconds_total, 'chunk_sec': seconds, 'overlap_sec': overlap})
        return {'segments': segments, 'language': 'es'}
    finally:
        if client:
            client.close()
