# Provenance

Runtime does not import `/home/siamarino/ai-dubbing/pipeline`. The following behavior was ported.

| Behavior | Source |
| --- | --- |
| `trim_silence` (RMS 0.005, 10 ms mean-square window, pad ms) | `pipeline/src/audio_io.py` |
| Interval collision and EOF clamp | `pipeline/src/placement.py` |
| Assembler: fade 5 ms, never overwrite an earlier placed line | `pipeline/src/assembler.py` |
| Qwen load and `GEN_SETTINGS` | `pipeline/src/backend.py` `Qwen3TTSBackend` |
| qwen-full fit rules: no shorten, no retry loop, trim then tempo ≤ 1.10, window = start → next start | `pipeline/run_pipeline.py` (`fit_rules == qwen-full`) and `pipeline/src/scheduler.py` |
| Game stereo + centered English voice, gain 1.0 if sum peak ≤ 0.99 | Post-step described in `pipeline/reports/sample_video.md` |
| Whisper invocation | Flags used for `sample.mp4`, confirmed against `whisper --help` |

Reference B audio stays at `/home/siamarino/audios/04_referencia_ingles_emocion.wav`. This repo stores only the user-confirmed transcript.
