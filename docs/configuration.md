# Configuration

Selection: `--config` > `AIDUB_CONFIG` > ignored `config/local.json` > portable `config/default.json`. The launcher resolves the selected interpreter before importing the CLI. Executable names use PATH; relative paths use the checkout root. Copy the complete example into local config and fill in existing environment, model and reference paths. Config files are complete snapshots, not implicit merges.

New `init` checks executable permissions, reference approval, local source/verification Whisper weights, local Qwen weights, CUDA availability and provider configuration for auto jobs. Preflight makes no provider request and permits no model download. No CPU synthesis fallback or provider fallback exists. Existing jobs keep their config snapshots and legacy synthesis keys; current portable defaults are not imposed on them.

| Group | Settings |
| --- | --- |
| `executables` | `python_qwen`, `whisper`, `ffmpeg`, `ffprobe`; Whisper's Python is adjacent to its venv CLI |
| `models` | `qwen_path` snapshot directory; `whisper_path` .pt file; empty resolves existing local cache only |
| `reference` | WAV, transcript file, optional `expected_text_sha256`; otherwise reference B's locked transcript applies |
| `audio_mapping` | Audio ordinals, not absolute indices. Default roles are placeholders until listened to for each source |
| `transcription` | `chunk_sec=600`, `overlap_sec=2`; words belong to one core window by midpoint |
| `processing` | `block_frames=65536`, valid 128..1048576; `storage_reserve_bytes` optionally adjusts the disk estimate reserve |
| `batching` | `max_cues=40`, `max_chars=24000`, including context |
| `providers` | Explicit command or OpenAI-compatible translation/repair; `timeout_sec=900`, `max_attempts=2` (1..5), `max_response_bytes=1048576` |
| `timeouts` | Worker startup 180s; candidate ASR 180s; source ASR window 1800s; tempo 180s; probe 1200s; media 10800s |
| `quality` | Candidate `asr_model`/`asr_model_path`, `asr_language`, `asr_device`; `speaker_proxy_enabled`; bounded retries and checker tag |
| `segmentation` | Locked RMS/onset/merge settings; `quiet_speech_heuristic`; `untranscribed_energy_policy=partial` or explicit reviewed `warn` |
| `mix` | `limiter=0.99` voice sum ceiling; `min_voice_gain=0.1`; `headroom_policy=partial` or `fail`. Game gain is always 1 |
| `export` | `container=mp4` or `mkv`; no picture re-encoding |

Qwen model, dtype, attention, English ICL, original trim RMS/window/pad, and tempo 1.10 remain fixed. New jobs freeze the local Qwen snapshot revision and model paths. Legacy jobs do not acquire a new synthesis revision key automatically.

To alter a stopped existing job, edit its `jobs/NAME/config.json`. Verification-only changes miss quality cache keys but reuse synthesis. Changing source/segmentation inputs can replace the timeline and require new translations. Invalid configurations fail with diagnostics; deleting caches is not a recovery step. See `docs/architecture.md` for checkpoint migration.
