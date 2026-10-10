# Gameplay dubbing

Turn Spanish microphone commentary from an OBS recording into English Qwen voice-clone speech, mixed with the continuous original game bed. The picture is stream-copied. `auto` uses configured translation/repair providers; the manual JSON handoffs remain available.

This development branch has regression tests, controlled media fixtures and a configured 81-second model run with interruption/resume. That run exported **partial** because six source-energy spans lack transcript text, despite all 26 kept cues being placed. No representative 1–2 hour model run has passed. Technical validation is separate from human listening approval.

## What runs

| Stage | Implementation and outputs |
| --- | --- |
| Inspect | FFprobe records audio ordinals and absolute indices. Missing video duration is resolved from video packet presentation timestamps. Codec/container compatibility and storage budget are checked before extraction. `inspect/probe.json` records duration confidence. |
| Extract | FFmpeg selects mic and game independently with `0:a:N`, without seeking or resetting their origins. Finished tracks have independent fingerprints. Only headers are loaded to check alignment. |
| Transcribe | One local Whisper worker processes overlapping 10-minute mic windows sequentially. Each window is checkpointed. Word midpoints assign overlap words to one window. An indexed disk energy map adjusts/merges approximate Whisper cues; it does not invent text for untranscribed energy. |
| Translate | Stable cue IDs are batched, with read-only neighboring context. Every matching saved batch response is checked and reused. Manual `accept-translation` uses the same schema. |
| Synthesize / verify / fit | One shared Qwen backend and clone prompt per process. Generated WAVs have content-addressed caches. One candidate ASR worker per schedule pass; bounded quality and fit seeds, tempo up to 1.10, optional movement into preceding silence, then compact repair. |
| Mix | Bounded PCM blocks and one cue at a time. Quiet generated margins/fades apply only to voice. Peak management changes each cue's voice gain; game samples are not scaled, gated, faded, or time-stretched. |
| Export / validate | Source video copy, one English AAC track, Spanish comparison by stream copy, SRT for placed cues only. Decode, video bitstream identity, timing/length, voice verification, headroom and PCM game-bed checks are recorded separately. Missing frame counts are reported as unavailable. |

## Quality preset

For new jobs where correct, natural English matters more than runtime, add `--preset quality`:

```bash
bin/aidub auto /absolute/path/recording.mp4 --name recording_en \
  --mic-ordinal 2 --game-ordinal 1 --mixed-ordinal 0 --preset quality
```

It adds a second ASR hearing for doubtful speech and voiced gaps, whole-transcript context with a glossary, utterance-aware translation with soft syllable budgets, a separate bilingual review with an audit trail, best-of-N voice takes with sequence-aware text checks, one consistent presentation path for every take (including tempo-adjusted ones), and a risk-ranked listening report. Qwen generation, ICL, reference B, trim and max tempo 1.10 are unchanged. Existing jobs keep their snapshots. See [docs/quality.md](docs/quality.md); short-sample evidence is in [runs/quality/REPORT.md](runs/quality/REPORT.md).

## Fresh clone setup

Use Linux, FFmpeg/FFprobe, and a compatible NVIDIA CUDA environment. Qwen synthesis refuses CPU fallback. This repository does not install anything or download models on execution. Provision the environments and weights yourself before running it.

The observed environments are Python 3.12.14 for Qwen and Python 3.11.16 for Whisper. `requirements-runtime.txt`, `requirements-qwen.txt`, and `requirements-whisper.txt` record observed package pins. The Qwen environment has Torch/Torchaudio `2.11.0+cu130`; the current Whisper environment has Torch `2.14.0+cu132`. The pair ran the short sample on this workstation. These are top-level observed pins, not a complete lock of transitive dependencies; a fresh installation was not verified during hardening.

A reproducible provisioning procedure is:

1. Create separate Python virtual environments for Qwen and Whisper.
2. Install matching Torch CUDA wheels appropriate for those observed pins and your host driver, using your approved wheel source. Do not assume a CPU wheel will run Qwen.
3. Install `requirements-qwen.txt` in the Qwen environment and `requirements-whisper.txt` in the Whisper environment. The latter also needs FFmpeg on the host. The lightweight CLI/test dependencies are in `requirements-runtime.txt`.
4. Provision the `Qwen/Qwen3-TTS-12Hz-1.7B-Base` snapshot and Whisper Turbo weights locally. Model files are excluded from Git. Missing weights fail preflight; no model is downloaded as a fallback.
5. Copy `config/example.json` to ignored `config/local.json`, then configure executable, model, reference, and provider paths.

```bash
cp config/example.json config/local.json
# Edit config/local.json for your environments, pre-existing weights and reference.
bin/aidub --config config/local.json --help
```

Configuration selection is explicit `--config`, then `AIDUB_CONFIG`, then `config/local.json` if present, then the portable default. The launcher chooses its interpreter from that selected config. Relative asset/model paths are based on this checkout; an explicit config filename is relative to the invoking directory. Executable names such as `python3` can be resolved through PATH. An explicit config works even when the default interpreter path is unusable.

On Santiago's workstation the previous default was preserved in ignored `config/local.json`. Existing jobs keep their own configuration snapshots and paths to their original environments. Updating the portable defaults does not overwrite them. No existing job, model, recording, or environment needs to be deleted.

### Model and voice requirements

Use `models.qwen_path` for a complete local snapshot directory and `models.whisper_path` for a pre-existing `.pt` file, or leave them empty to resolve the existing local model caches. New jobs freeze the Qwen snapshot revision and absolute local weights paths. Legacy synthesis keys remain compatible for old jobs.

Reference B's WAV is not distributed. Configure `reference.wav` and `reference.text_file` with the exact spoken transcript. Reference B's confirmed transcript and synthesis/trim settings remain unchanged. Another speaker can supply an explicit SHA-256 of the stripped UTF-8 transcript as `reference.expected_text_sha256`; this makes the reference approval explicit without editing code. Do not mismatch a reference waveform and transcript.

`quality.asr_model`/`asr_model_path` select candidate verification weights separately from source transcription. `quality.asr_language` defaults to language detection. The example uses CPU for candidate ASR; CUDA is configurable and falls back to CPU on a worker failure. Source transcription and Qwen execute sequentially; no parallel synthesis pool is introduced.

### Providers

Both providers must be configured for `auto`. Command providers take an argv list with `{request}`, `{response}` and `{role}` placeholders; the default working directory is the checkout, or set `cwd` explicitly. They write a JSON response file or print a JSON object. OpenAI-compatible providers use an explicit URL/model and a credential environment variable; credentials must remain outside tracked configuration.

```json
{
  "providers": {
    "translation": {
      "kind": "command",
      "command": ["python3", "scripts/provider_cursor_agent.py", "--agent", "/path/to/cursor-agent", "--request", "{request}", "--response", "{response}", "--role", "{role}"],
      "timeout_sec": 900,
      "max_attempts": 2
    },
    "repair": {
      "kind": "openai_compatible",
      "base_url": "https://your-provider.example/v1",
      "model": "your-configured-model",
      "api_key_env": "AIDUB_REPAIR_API_KEY",
      "timeout_sec": 900,
      "max_attempts": 2
    }
  }
}
```

Cursor is an optional adapter. It uses the configured host binary/account, not an embedded credential or a replacement provider. Requests include validation feedback on retries. There is no provider fallback.

## Recordings and commands

Use separate mixed/game/mic audio tracks. An **audio ordinal** counts audio streams from zero; an **absolute index** counts all container streams. For example, video index 0 and audio indices 1/2/3 correspond to audio ordinals 0/1/2. Generic OBS track names do not establish the roles. Listen to short extracts first; mixed minus game should match the mic. Set the ordinals for each recording.

MP4 and MKV inputs can be probed. The default output is MP4, with a conservative copied-codec compatibility check. Set `export.container` to `mkv` for another supported container instead of re-encoding the picture. Negative relative audio offsets, mismatched mic/game origins, mono game tracks, and game audio extending past the established video endpoint fail explicitly.

```bash
bin/aidub auto /absolute/path/recording.mkv --name recording_en \
  --mic-ordinal 2 --game-ordinal 1 --mixed-ordinal 0
# Repeat the same command to resume the same job/source.
bin/aidub status recording_en
bin/aidub validate recording_en
```

`validate` displays the saved report; it does not rerun validation. `run`/`resume` execute ready stages without invoking providers:

```bash
bin/aidub init /absolute/path/recording.mp4 --name manual_clip \
  --mic-ordinal 2 --game-ordinal 1 --mixed-ordinal 0
bin/aidub run manual_clip
bin/aidub accept-translation manual_clip /absolute/path/translation.json
bin/aidub resume manual_clip
bin/aidub accept-repair manual_clip /absolute/path/repair.json
bin/aidub resume manual_clip
```

`export-translation` and `export-repair` remain available. The validators reject missing/duplicate/extra IDs, empty English, and response timing edits. Repair requires a reason and a changed line or explicit `leave_unresolved`.

## Resume, errors and status

One nonblocking OS job lock covers initialization, stages, provider calls and acceptance. Manual writers follow the same lock strategy. A competing runner exits with a lock diagnostic. Locks release when processes exit; **never delete LOCK to bypass a live runner**, and the leftover file does not itself mean a lock is held.

Stage fingerprints and atomic metadata preserve completed work. Batched responses have identities bound to their request, provider and repair source text. Response files saved before acceptance are recovered and validated. Each attempt's request, response, stdout/stderr and state are retained under `handoff/batches/`. Budgets persist across resumes; after exhaustion, fix the cause and explicitly increase `max_attempts` (up to 5) in the stopped job's config to allow another attempt.

An external provider can finish without its response being durably saved. The next resume records an **uncertain completion/billing outcome** and may use a remaining attempt. Exactly-once billing is not claimed. Provider errors return 1 while preserving a resumable handoff state and a manifest error. Source/model/worker failures are recorded as failed with logs; resume after fixing the cause.

Quality results are keyed by generated WAV bytes, synthesis identity, reference hash, checker source/version, quality settings, candidate ASR weights/language and environment versions. Verification-only edits reuse synthesis and rerun checks. Legacy per-line quality scores are ignored; existing WAV synthesis caches and valid legacy transcript cue IDs are retained. Changing transcript/segmentation inputs can change cue IDs and requires new translation batches. Configuration changes must be made while the job is stopped.

Exit codes: 0 complete; 3 partial; 2 manual handoff needed; 1 failure. `complete` requires every kept cue placed and required technical gates passed. Unavailable frame counts are not counted as passes; copied-video identity is a separate required gate. Approximate container duration, unreviewed source energy gaps, missing verification or insufficient game headroom prevent complete status. A partial export is explicitly named `english_PARTIAL.mp4`/`.mkv`; only placed cues appear in subtitles. Previous artifacts may remain on disk; use the manifest/report's current output path.

## Voice and peak policy

For an unadjusted sum above `mix.limiter`, the mixer finds a safe **voice-only gain per cue**, so quiet portions retain the original bed. If a cue's safe gain falls below `mix.min_voice_gain` (default 0.1), that cue remains unplaced with `insufficient_game_headroom`. If the source game itself exceeds the ceiling, its samples remain unchanged: default `headroom_policy=partial` records the limitation and exports a partial result; `fail` refuses finalized output. The policy is deliberate; global game attenuation is not a fallback. Voice PCM is stored after its actual gain, and validation compares `mix = game + actual voice` in blocks. AAC is encoded once for playback; this is continuous PCM-bed preservation, not an audio packet-identity claim. Decoded export audio is checked separately for non-finite samples and full-scale overshoot; a codec overshoot makes the result partial and is reported, without silently changing the game bed.

The optional `segmentation.quiet_speech_heuristic` is a harmonic/noise second look at low-energy text; it is not speech recognition. Untranscribed energy is recorded, with a default partial policy; `untranscribed_energy_policy=warn` is an explicit reviewed override. The optional `quality.speaker_proxy_enabled` compares pitch and brightness; it is not a speaker embedding or proof of identity. Token-based ASR checks miss some ordering/repetition errors and can reject valid names or short reactions. These heuristics have not been broadened into language/identity guarantees.

Listen against `spanish_compare`, inspect quiet game stretches, and check reactions, names, timing, clicks, omissions and voice drift. Neither complete nor partial is a listening approval.

## Resources and diagnostics

At 48 kHz, two hours of stereo PCM16 is about 1.38 GB per extracted track; FLOAT stereo mix about 2.76 GB, FLOAT mono voice about 1.38 GB. Mic windows and synthesis retries add disk use. English and Spanish comparison exports each copy the picture, so budget approximately two additional video-sized outputs. The input recording is never duplicated for processing. Preflight estimates free space; the estimate cannot predict all synthesis retry lengths. Check disk during very large jobs.

Full-recording audio work is bounded by `processing.block_frames` (default 65536), a single cue, and metadata. Whisper windows default to 600 seconds with two-second overlap; provider batches default to 40 cues / 24000 serialized characters including context. This controls allocations and request size, but metadata/energy index size grows with the content. Long-duration throughput, storage and current GPU model compatibility remain host validation tasks.

| Evidence | Job path |
| --- | --- |
| State/error | `manifest.json` |
| Duration, mapping, storage estimate | `inspect/probe.json` |
| ASR logs / windows | `transcribe/whisper.log`, `transcribe/generated_worker.log`, `transcribe/chunks/` |
| Drops, energy gaps, uncertainty | `transcribe/corrections.json` |
| Provider attempts / billing uncertainty | `handoff/batches/`, `report/timings.json` |
| Synthesis / independent quality cache | `cache/synth/`, `cache/quality/` |
| Fit / final placement and voice gains | `schedule/summary.json`, `mix/placed_summary.json`, `mix/gain.json` |
| Timing / process peak RAM | `report/stage_metrics.jsonl` |
| Decode/bitstream and technical gates | `report/validation.json`, `report/validation.md`, `report/*_decode.log` |

`timeouts` configures worker startup, candidate/chunk ASR, tempo, probe and media budgets. Provider budgets live in each provider spec. Qwen cache metadata records its process's inference wall time and peak GPU allocation; it does not measure another worker's VRAM. See [host verification](docs/host-verification.md) and [hardening verification](docs/hardening-verification.md) for measured facts and remaining checks.

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. /path/to/qwen-env/bin/python -m unittest discover -s tests -v
```
