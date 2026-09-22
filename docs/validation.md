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

- 1–2 hour recordings. An 18-minute file is not that proof. The runner does not load video frames or speak the whole transcript at once; a long file has not been timed.
- Perceptual sync and voice quality on any clip the user has not listened to.

## Second recording

Date: 2026-09-22. Job: `jobs/re4_20260922_193906` (not in Git).

Input: `/mnt/windows/Users/santi/Videos/2026-09-22 19-39-06.mp4`. OBS, 1094.283333 s, 65657 frames, md5 `89904e4d415b3ab0a5498985ea73fde2`. Read-only NTFS mount. Job files stayed on the Linux filesystem.

Status: **PARTIAL**. 327/336 placed. Nine lines still missed the window after one alternate seed and one compact revision. This is not a listening approval and not evidence for a 1–2 hour recording.

English video:

`/home/siamarino/ai-dubbing-e2e/jobs/re4_20260922_193906/output/english_PARTIAL.mp4`

### Audio ordinals

Stream names are `simple_aac_recording0/1/2`. Short extracts at 90 s, 420 s, and 780 s: mixed minus game matched the microphone (residual correlation about 0.998). Init used `--mic-ordinal 2 --game-ordinal 1 --mixed-ordinal 0`. Probe recorded mic ordinal 2 / absolute index 3, game 1 / 2, mixed 0 / 1. All audio starts 0.0. Trailing pad 1568 samples at 48 kHz.

### Measured result

| Item | Value |
| --- | --- |
| Inspect + extract + Whisper wall | 59 s (Whisper frames about 37 s) |
| Segments kept / dropped | 336 / 44 no-energy |
| Uncertain words | 131, not rewritten |
| First synthesis wall | 546 s, 336 cache misses |
| Repair synthesis wall | 137 s, 23 fresh, 324 hits |
| Repair-pass load / prompt | 4.444 s / 0.655 s |
| Cache wavs | 393 (336 primary, 34 alternate, 23 revision) |
| Inference time in cache metadata | 571.077 s |
| Peak VRAM in cache metadata | 4.644 GiB |
| Placed / unplaced | 327 / 9 |
| Tempo adjusted | 3 |
| Unplaced ids | 27, 66, 146, 148, 172, 195, 252, 280, 312 |
| Mix gain / peak / clip samples | 1.0 / 0.437 / 0 |
| English video | h264 copy, 65657 frames, 1094.283333 s, one default `eng` AAC, 2.2 GB |
| Spanish compare | 65657 frames, mixed ordinal 0, `spa` |
| Both files | decode clean |
| English mix vs Spanish mic | residual of mix minus game matched the English voice (correlation 1.0) and not the microphone (about 0.01) |

`bin/aidub resume re4_20260922_193906` after the partial export took 68 s. It printed `schedule: unchanged` and `mix: unchanged`, did not load Qwen, and left the cache at 393 wavs. Exit code 3.

Input md5 and reference B md5 `a5923bfa6cc5ae580f5031e0dc9ef059` were unchanged. Docker `qwen38-27b-rtx3090-single-1` stayed `Exited (0)`.
