# Troubleshooting

- Missing executable/model/reference: configure ignored local config before `init`. Select it with `--config`. Model downloads and environment installation are never automatic.
- CUDA unavailable: verify the host driver and configured environment. Qwen cannot synthesize on CPU. Do not stop other services or replace packages simply to make preflight pass.
- Wrong audio roles: ordinals count audio streams; labels do not prove their roles. Listen to extracts and create a correctly mapped new job. The pipeline does not separate already-mixed audio.
- LOCK: another process holds an OS lock. Wait for exit; do not delete the inode while a runner is active. A file left after exit needs no cleanup.
- Provider failure: `status` exposes a persisted manifest error and resumable handoff. Inspect the identity-bound attempt state/logs under `handoff/batches`. Fix configuration; bounded attempt budgets persist. An explicitly increased `max_attempts` permits another attempt. Missing durable responses can incur another paid call; billing uncertainty is recorded.
- Worker crash/hang: inspect `transcribe/whisper.log` or `generated_worker.log`. Startup and per-request timeouts are separate; workers are shut down before retry/fallback. Stdout is reserved for JSON.
- Partial headroom result: game audio was preserved. Inspect per-cue voice gains and `insufficient_game_headroom`, plus source over-ceiling counts. The partial policy does not silently attenuate the game. Choose a recording/voice balance with adequate headroom and listen before changing minimum gain/policy.
- Missing MKV timing: video packet timestamps are preferred. Container fallback is approximate and cannot justify complete status. Choose a compatible output container; the picture is not re-encoded.
- Source energy gaps: inspect `transcribe/corrections.json`. Energy is not proof of speech, and the default partial policy is conservative. A reviewed `warn` policy is explicit.
- Changed checker/model settings: old generated audio is reused where synthesis identity matches, but verification runs again. Legacy quality scores are ignored. Do not delete caches to force recovery.
- Large jobs: inspect free disk, `stage_metrics.jsonl`, window/provider checkpoints and configurable timeouts. WAVs, two copied video exports and retry caches consume space even though processing RAM is bounded. Source ASR window boundaries and heuristic quality gates still need representative host validation.

Use the current output path recorded in the manifest/report. Previous complete/partial files can remain as historical artifacts. `validate` only prints the saved report; `resume` runs ready stages. A technical pass never replaces listening.
