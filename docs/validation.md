# Validation run

Date: 2026-09-22. Job: `jobs/sample_e2e` (not in Git).

## Status

The CLI was implemented and exercised on `/home/siamarino/audios/sample.mp4`.

Sample status: **COMPLETE**. 25/25 segments placed. This is not a listening approval and not evidence for a second clip or a 1–2 hour recording.

English video:

`/home/siamarino/ai-dubbing-e2e/jobs/sample_e2e/output/english.mp4`

## What was actually run

Fresh stages, not a replay of `pipeline/output/sample_video/`:

1. Probe and extract. Mic ordinal 2 (absolute stream 3), game ordinal 1 (absolute stream 2). No `-ss`.
2. Whisper Turbo, Spanish, word timestamps, CUDA, on the mic-only wav.
3. Agent translation of the generated request (`xai/grok-4.7`, agent-assisted). 25 lines.
4. Qwen3-TTS reference B, ICL, 25 primary seeds (`42+id`). All cache misses.
5. Id 20 did not fit. One alternate seed. Then one compact repair. Then mix and validate.
6. `bin/aidub resume sample_e2e` after completion printed `schedule: unchanged` and `mix: unchanged`, did not load Qwen, and left the cache at 27 wavs.

Historical reference-B work only exported a 24.700 s preview. This job is the full 81.716667 s export. The older unplaced ids A=26 and B=14 are not this timeline.

## Measured result

| Item | Value |
| --- | --- |
| Segments kept / dropped | 25 / 8 no-energy or empty |
| Placed | 25 |
| Tempo adjusted | 0 |
| Unplaced | none |
| Synthesis files | 27 (25 primary, 1 alternate, 1 revision) |
| Inference time in cache metadata | 34.384 s |
| Repair-pass load / prompt | 4.581 s / 0.692 s |
| Peak VRAM in cache metadata | 4.643 GiB |
| Mix gain / peak / clip samples | 1.0 / 0.362 / 0 |
| English video | h264 copy, 4903 frames, 81.716667 s, one default `eng` AAC |
| Spanish compare | 4903 frames, original mixed audio 81.685 s |
| Both files | decode clean |

Id 20 source: `Estamos dentro Estamos dentro de la iglesia Vamos, vamos`.

- Primary seed 62: trim 2.707 s vs window 2.567 s. Needed tempo 1.055, within 1.10, but ffmpeg `atempo` landed at 2.574 s (`still_overrun_after_tempo`, 7 ms over).
- Alternate seed 162: trim 3.180 s, `overrun_tempo_limit`.
- Repair, agent-assisted: `We're inside the church. Let's go, let's go.` Reason: the first "we're inside" is restated by "we're inside the church"; church and the repeated let's-go were kept.
- Revision seed 62: trim 2.109 s, `fit_unchanged`.

The job report's "fresh synthesis: 1 / cache hits: 24" is the repair pass only. The first pass synthesized every primary line. Cache metadata is the cumulative record.

## Segmentation

Automatic Whisper segments plus RMS 0.005 energy onset. Not the hand-refined 27-line timeline. Drops matched the earlier no-energy hallucinations (`Adentro`, repeated `Espero que por acá`, `Gracias por ver el video`). Some adjacent lines merged because the energy gap was ≤ 0.12 s, including the id 20 line that needed repair. Prior "excellent reaction timing" was about that older timeline. It is not claimed here.

## Preservation

Unchanged md5:

- `sample.mp4` `cb4d03559f7b3f92aa1534cd280bea15`
- `04_referencia_ingles_emocion.wav` `a5923bfa6cc5ae580f5031e0dc9ef059`
- `pipeline/config/default.json` `60e382d6216660b34b74765fe0f1ffac`

Docker `qwen38-27b-rtx3090-single-1` remained `Exited (0)`. SoX and flash-attn warnings appeared and were ignored.

## Tests

`python -m unittest discover -s tests` using the Qwen venv: 22 tests, OK. They cover ordinal-vs-index mapping, offsets, the 1.10 tempo cap, handoff rejection, cache keys, resume fingerprints, SRT omission, and overlap. They do not run GPU synthesis.

## Not validated

- A second unseen recording. Still required before treating the tool as generally accepted.
- 1–2 hour recordings. The runner does not load video frames or speak the whole transcript at once; that has not been timed.
- Perceptual sync and voice quality. The user has to listen.
