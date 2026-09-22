# Implementation plan

No applicable `AGENTS.md` existed in `/home/siamarino/ai-dubbing` or this directory before this project. Unrelated `AGENTS.md` files in other repositories were not used.

## What already works

- Whisper Turbo CLI in `/home/siamarino/ai-dubbing/whisper/.venv` (`openai-whisper==20250625`). Cached weights: `~/.cache/whisper/large-v3-turbo.pt`. Flags verified with `whisper --help`: `--model turbo --language Spanish --task transcribe --word_timestamps True --device cuda --output_format json`.
- Qwen3-TTS in `/home/siamarino/ai-dubbing/qwen3-tts/.venv` (`Qwen3TTSModel.from_pretrained`, `create_voice_clone_prompt`, `generate_voice_clone`). Validated settings live in `pipeline/src/backend.py`: CUDA, bfloat16, SDPA, English, ICL `x_vector_only_mode=False`, and the `GEN_SETTINGS` dict. SoX and flash-attn warnings are non-fatal.
- Scheduling policy for the accepted gameplay dub is the qwen-full path in `pipeline/run_pipeline.py` and `pipeline/src/scheduler.py`: window = start → next start (last → source end), trim RMS 0.005 with a 10 ms mean-square window and pad 0 ms before tempo, `atempo` ≤ 1.10, no later-line shift, unplaced stay silent. Trim implementation is `pipeline/src/audio_io.py:trim_silence`. Overlap policy is `pipeline/src/assembler.py` (never overwrite an earlier line).
- `sample.mp4` stream layout is documented in `pipeline/reports/sample_video.md` and was user-confirmed by listening: audio ordinal 0 mixed, 1 game, 2 mic. Ordinals are not absolute stream indices. All streams start at 0. Video 81.716667 s (4903 frames @ 60). Audio 81.685 s. Trailing pad only, 1520 samples at 48 kHz.
- Reference B file is 21.842 s, already inside 15–25 s, used as-is. Confirmed transcript is stored verbatim in this repo. Do not change historical `pipeline/config/default.json` (still points at reference A).

## Discrepancy

`pipeline/reports/sample_video_ref_ab.md` lists full-timeline unplaced ids A=26 and B=14. Those figures come from schedule JSON under `output/sample_video_ref_ab/{A,B}/segments/`. The only B video artifact is `B/preview.mp4` (24.700 s, segments 1–8). That is not evidence of a full-duration B video export. This project does not treat that excerpt as a finished dub.

## What this project integrates

A new agent-operated CLI. It does not import the historical package at runtime. Ported pieces are listed in `PROVENANCE.md`.

Stages: inspect → extract → transcribe → translation handoff → synthesize → schedule → mix/mux → validate.

Translation and compact repair are file handoffs to the coding agent already in the session. No paid API, no Docker LLM, no CosyVoice, no new models.

## Decisions

- Runtime Python is the existing Qwen venv (numpy, soundfile, torch, torchaudio). Whisper is a subprocess of its own venv. No package installs.
- Job config is snapshotted at `init`. Jobs live under this repo's `jobs/` and are gitignored.
- Cache key is text + reference wav hash + reference text + seed + Qwen generation settings. Translation edits invalidate only affected synthesis and downstream mix, not transcription.
- Repair budget for new jobs: one alternate seed (`seed + 100`), then one compact-translation revision, then unresolved. Tempo ≤ 1.10 still applies inside an attempt. Historical comparison texts are not edited.
- English mix is game-only stereo plus centered voice (voice copied to L and R, matching the sample mix). Gain 1.0 unless the sum peak exceeds 0.99.
- Segmentation automates the documented sample rules: Whisper segments, RMS 0.005 / 10 ms energy onset, drop no-energy lines, do not invent text for untranscribed energy, merge only across a short silence. It is not a byte copy of the hand-refined 27-line timeline. Reaction timing approved on that older timeline is not claimed for a fresh segmentation.

## Not claimed

`sample.mp4` does not validate 1–2 hour recordings. A later 18-minute clip is recorded in `docs/validation.md` as partial, not as general acceptance.

## Implemented

The CLI, tests, and `docs/validation.md` record a complete `sample_e2e` run. Id 20 needed the repair handoff after a legal tempo still missed the window by 7 ms. Resume after completion did not reload Qwen.
