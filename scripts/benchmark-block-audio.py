#!/usr/bin/env python3
"""Synthetic duration benchmark; not a real video/model reliability check."""
import argparse
import json
import resource
import time
from pathlib import Path

import numpy as np
import soundfile as sf

from aidub.energy import EnergyIndex
from aidub.streaming import alignment_meta, stream_mix, validate_audio_files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--seconds', type=int, default=3600)
    args = parser.parse_args()
    if args.seconds < 5:
        parser.error('seconds must be at least 5')
    args.directory.mkdir(parents=True, exist_ok=False)
    root, sr, block = args.directory, 48000, 65536
    frames = args.seconds * sr
    started = time.perf_counter()
    game = root / 'synthetic_game.wav'
    with sf.SoundFile(game, 'w', samplerate=sr, channels=2, subtype='PCM_16') as out:
        for start in range(0, frames, block):
            t = np.arange(start, min(frames, start + block)) / sr
            signal = (.8 * np.sin(2 * np.pi * 220 * t)).astype('float32')
            out.write(np.stack((signal, signal), axis=1))
    generation_seconds = time.perf_counter() - started
    voice = root / 'synthetic_voice.wav'
    signal = (.6 * np.sin(2 * np.pi * 220 * np.arange(sr // 5) / sr)).astype('float32')
    sf.write(voice, signal, sr, subtype='FLOAT')
    cfg = {'processing': {'block_frames': block},
           'mix': {'limiter': .99, 'min_voice_gain': .1, 'headroom_policy': 'partial'}}
    rows = [{'id': i, 'start': start, 'placement_start': start, 'placed': True,
             'used_path': str(voice)} for i, start in enumerate([1, args.seconds / 2, args.seconds - 1])]
    meta = alignment_meta(frames, sr, 0, 0, args.seconds)
    began = time.perf_counter()
    gain = stream_mix(game, rows, root / 'mix', sr, meta, cfg)
    mix_seconds = time.perf_counter() - began
    began = time.perf_counter()
    validation = validate_audio_files(game, root / 'mix/english_voice.wav', root / 'mix/english_mix.wav', sr, meta, cfg)
    validation_seconds = time.perf_counter() - began
    began = time.perf_counter()
    with sf.SoundFile(game) as handle:
        def reader(start, count):
            handle.seek(start)
            return handle.read(count, dtype='float32', always_2d=True).mean(axis=1)
        index = EnergyIndex.build(reader, frames, sr, .005, .01, block, root / 'energy.sqlite')
        voiced_frames = index.count(0, frames)
        index.close()
    report = {'synthetic': True, 'duration_seconds': args.seconds, 'sample_rate': sr,
              'frames': frames, 'block_frames': block, 'generation_seconds': generation_seconds,
              'mix_seconds': mix_seconds, 'validation_seconds': validation_seconds,
              'energy_seconds': time.perf_counter() - began, 'voiced_frames': voiced_frames,
              'wall_seconds': time.perf_counter() - started,
              'process_peak_ram_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
              'kept': len(rows), 'placed': sum(r['placed'] for r in rows),
              'gain': gain, 'validation': validation,
              'disk_bytes': sum(p.stat().st_size for p in root.rglob('*') if p.is_file())}
    (root / 'benchmark.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    if not validation['shape_ok'] or validation['game_bed_error'] > 1e-6 or not all(r['placed'] for r in rows):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
