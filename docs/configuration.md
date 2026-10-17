# Configuration

For the explicit subscription-only Luna primary provider, prerequisites, all
five role settings, authentication and migration rules, see
[Luna provider](luna-provider.md). Portable defaults stay unconfigured; local
executable/reference paths and credentials do not belong in published config.

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
| `whisper.decode_options` | Optional source-ASR decoding (`condition_on_previous_text`, `beam_size`, `best_of`, `temperature`, `initial_prompt`, ...). Absent means the previous Whisper defaults |
| `asr_second_pass` | Quality preset: `enabled`, `model`/`model_path` (local weights only), `device`, padding and acceptance thresholds, decoding `options` |
| `translation_quality` | Quality preset: `english_syllables_per_sec`, context size, neighbours, utterance grouping, `join` (short-pause takes), `review` (`max_rounds` 1..4, `back_translation=disputed` or `off`) |
| `voice_selection` | Quality preset: best-of-N `candidates` (1..8), `max_extra_attempts` (0..8), pacing bands, score weights |
| `voice_edge.presentation_version` | `2` applies margins, loudness, tempo and window bound identically to every take; `adaptive` margin floor/maxima; `source_loudness` slope and ±dB bound. Absent keeps the legacy path for old snapshots |
| `quality.text_checker` | `sequence-v1` for sequence-aware synthesized-text checks; `second_verification` re-hears disputed takes once |
| `risk_report` | `enabled`, number of `excerpts`, `previews` |
| `providers.context/review/back_translation` | Full specs or explicit `{"kind": "same_as", "role": "translation"}` aliases |

Presets live in `config/presets/`. `init`/`auto --preset NAME` merges each preset group one level deep into the selected config before the snapshot is written. Provider aliases fill missing/unconfigured roles and preserve explicitly configured role settings. A preset given for an existing job is ignored with a notice.

Qwen model, dtype, attention, English ICL, original trim RMS/window/pad, and tempo 1.10 remain fixed. New jobs freeze the local Qwen snapshot revision and model paths. Legacy jobs do not acquire a new synthesis revision key automatically.

### Optional Spanish comparison

`export.spanish_compare` is a strict boolean. New job creation writes an explicit
`false`, including when the selected local config predates this option. Set
`true` explicitly before creating a job to request the full comparison in its
configured MP4/MKV container. Portable defaults are off.

An existing snapshot with this field absent retains the historical **on** behavior.
Only an explicitly authorized stopped-job migration should add/change the field
in `jobs/NAME/config.json`; changing local/default config does not migrate it.
Resume then updates optional export and validation dependencies. The English
render, ASR, translation and takes remain reusable. Disabling retains any older
Spanish file but excludes it from current outputs, validation and storage credit.
Re-enable the prior setting to restore requested-comparison behavior; do not
delete jobs/caches or old files to migrate or roll back.

Comparison-only checks report **not requested**, never a pass, when disabled.
All English protections still validate against the original source and required
English files. Source previews select `mixed_ordinal` and the source picture's
time origin directly. A missing original makes Spanish previews unavailable;
an old comparison file does not stand in for current source validation.

To alter a stopped existing job, edit its `jobs/NAME/config.json`. Verification-only changes miss quality cache keys but reuse synthesis. Changing source/segmentation inputs can replace the timeline and require new translations. Invalid configurations fail with diagnostics; deleting caches is not a recovery step. See `docs/architecture.md` for checkpoint migration.

The optional `continuity` preset extends `quality` with `voice_selection.source_pacing`
(`enabled`, `weight=4.0`) and `voice_edge.presentation_version=3`. Its `protection`
settings are `floor_rms=0.0015`, `max_lead_ms=80`, `max_tail_ms=400`, `settle_ms=20`.
See [the measured continuity investigation](continuity.md) before changing existing
job snapshots. Presentation v3 rejects unpreservable endings and requires the
`generated_endings_preserved` gate.

The `performance` preset adds `source_events.enabled` (optional local
`annotations_file` bound to the microphone hash), `voice_selection.source_pauses`,
`source_pacing.use_source_span`, `search_for_placeable`, reaction-preserving joins,
and `voice_edge.protection.inspect_full_tail` with `max_analysis_tail_sec=2` and
`decay_floor_rms=0.0001`. Uncertain events, unintelligible source spans and disputed
translation reviews keep the job partial. See [performance.md](performance.md).

### Bounded automatic source resolution

New jobs with `source_events.enabled=true` materialize
`source_resolution: {"enabled": true, "max_semantic_rounds": 2}`; the performance
preset enables it explicitly. Existing snapshots lacking the block remain
unchanged. Do not add it to an active job. A stopped-job migration requires a
separately authorized snapshot change; retain all historical decisions and media.

`auto` resolves disputed source readings and unconfirmed English before scheduling.
It uses the configured review provider and already provisioned local Whisper model,
with at most one new contextual hearing and two semantic rounds per source-evidence
identity. Exact saved hearings are reused, and budgets survive resume. A last-round
revision remains unconfirmed. Back-translation cannot supply acoustic proof.

Minor grammatical/equivalent readings can be voiced when meaning is supported and
exact English is accepted. Material ambiguities remain visible when evidence cannot
decide. Divergent actor/action/number/referent or accent-sensitive grammar readings
require contextual acoustic support even when the ordinary text review missed the
dispute. Explicit punctuated discourse markers alone do not create that divergence.
Independent supported clauses require acoustic word boundaries, a second
review of exact child English/parts, stable lineage, and explicit unresolved
remainders. Event-bearing cues require scoped boundary reconciliation before a
partial split. Unknown periodic events and short noise hallucinations are not
turned into speech; only bound near-silence with empty lexical evidence can be
excluded automatically. Overlapping/implausible source boundaries block synthesis
before fit/repair attempts, without moving reaction anchors.

Original conflicts and prior text stay in history. `source_resolution` records bind
microphone, span, readings, acoustic model/options/provenance and exact reviewed
English. Acceptance, scheduling and validation share the eligibility reducer.
Malformed/contradictory source decisions fail validation; after provider attempts
are exhausted, independently valid saved rows can be retained while invalid rows
become explicit abstentions. Authentication, missing responses and uncertain
provider outcomes retain the provider helper's bounded recovery rules. No alternate
provider or billing path is substituted.

Manual `run`/`resume` stops at `awaiting_source_review`; `auto` holds the owned job
lock through resolution and acceptance. Evidence/budgets are in
`handoff/source_resolution/`; eligibility, remaining regions and boundary diagnostics
are in `report/source_resolution.json` and `report/source_boundaries.json`.
Technical partial status and all required English protections remain in force.
