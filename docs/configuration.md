# Configuration

`config/default.json` is copied into the job at `init`. Later edits to the default file do not change an existing job. Resume uses `jobs/<name>/config.json`.

## Executables

| Key | Role |
| --- | --- |
| `executables.python_qwen` | Interpreter for this CLI and for Qwen. Existing venv only. |
| `executables.whisper` | Whisper Turbo CLI. Separate venv. |
| `executables.ffmpeg` / `ffprobe` | Extract, atempo, mux, probe. |

`bin/aidub` reads `python_qwen` and refuses to create an environment.

## Streams

`audio_mapping.mic_ordinal`, `game_ordinal`, and `mixed_ordinal` select the Nth audio stream (`ffmpeg -map 0:a:N`). They are not container stream indexes. Defaults match `sample.mp4` after the user listened: 2 mic, 1 game, 0 mixed. Pass different ordinals to `init` for another recording. The three values must be distinct.

## Reference

`reference.wav` points at `/home/siamarino/audios/04_referencia_ingles_emocion.wav`. The wav is not copied into Git. `references/reference_b.txt` is the user-confirmed transcript, including spoken grammar (`this kind of dogs`, `he bite me`). The loader refuses a different transcript. Do not trim the wav in this project.

## Qwen

Fixed to the validated call: `Qwen/Qwen3-TTS-12Hz-1.7B-Base`, CUDA device map, bfloat16, SDPA, English, ICL `x_vector_only_mode=false`, and the generation dict in the config. The runner refuses other values.

## Schedule and mix

| Setting | Value | Meaning |
| --- | --- | --- |
| `seed_base` | 42 | Primary seed is `42 + segment id` |
| `alternate_seed_offset` | 100 | One extra attempt |
| `max_tempo` | 1.1 | Hard cap |
| `trim_rms` / `trim_window_sec` / `trim_pad_ms` | 0.005 / 0.01 / 0 | Validated trim |
| `fade_ms` | 5 | Edge fade after placement |
| `output_sr` | 48000 | Extract and mix rate |
| `mix.limiter` | 0.99 | Gain drops below 1 only above this peak |

## Segmentation

Whisper segments stay intact (internal pauses are not split). A start in silence moves to the next energy onset within `onset_lookback_sec`. Lines with no energy above RMS 0.005 are dropped and recorded. Voiced gaps with no words are recorded and not given invented text. Adjacent Whisper lines merge only when the silence between energy spans is ≤ `merge_max_silence_sec` (0.12 s). Low probability words are flagged, not rewritten. `anchor_type` is a duration/word-count heuristic.

## Docker

`docker_llm_container` is checked and must not be running. The pipeline never starts it.
