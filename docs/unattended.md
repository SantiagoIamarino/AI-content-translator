# Unattended run

`bin/aidub auto` is the one-command path. It keeps the manual commands. Qwen is loaded once per process and the voice-clone prompt is reused. Each line is checkpointed under `jobs/<name>/checkpoints/` and every candidate is appended to `jobs/<name>/ledger/candidates.jsonl`.

```bash
bin/aidub auto /path/to/recording.mp4 --name CLIP_NAME \
  --mic-ordinal MIC --game-ordinal GAME --mixed-ordinal MIXED
```

Exit codes match `run`: 0 complete, 3 partial, 1 failed, and a provider rejection is also 1. A partial export is `output/english_PARTIAL.mp4`. Complete still means the technical gates passed, not that anyone has listened.

## Provider configuration

Both `providers.translation` and `providers.repair` are required. This repo does not store API keys. If a kind is `unconfigured`, `auto` prints the shape below and stops. It does not switch to another provider.

Command provider. `{request}`, `{response}`, and `{role}` are replaced. `role` is `translation` or `repair`. The command must write the response file or print one JSON object. The response is checked with the same schema as `accept-translation` / `accept-repair`. One validation failure is sent back to the command; a second failure stops the job.

```json
{
  "kind": "command",
  "command": ["python3", "scripts/provider_cursor_agent.py", "--agent", "/path/to/agent", "--request", "{request}", "--response", "{response}", "--role", "{role}"],
  "timeout_sec": 900
}
```

`scripts/provider_cursor_agent.py` is one such command. It calls `cursor-agent` in ask mode and keeps `translator.kind` as `command`. It does not add a model name unless the agent process is itself configured with one. The workstation file `config/default.json` points at the local agent binary. `config/example.json` leaves both providers `unconfigured`.

OpenAI-compatible provider. Set the named environment variable in the shell that launches `auto`. Do not paste the key into JSON.

```json
{
  "kind": "openai_compatible",
  "base_url": "https://example.invalid/v1",
  "model": "model-id",
  "api_key_env": "AIDUB_TRANSLATION_API_KEY"
}
```

`base_url` and `model` may instead be supplied through `base_url_env` and `model_env`.

## What the extra passes do

Quality rejects a candidate for clipping, a hard cut inside the generated wav, missing or wrong words, the wrong language, or a wrong speaker. Wrong-speaker rejection needs both a pitch mismatch and a voiced-brightness mismatch. Brightness is the spectral centroid of pitched frames. Pitch is ignored under 0.45 s, so one score on a short phrase cannot reject it. The bright “Shotgun blast” take (Deepseek seed 49) is the regression: it is higher in pitch and brighter than reference B, and it is rejected. A darker or higher take that misses only one of those is kept. A rejected line is synthesized again, up to `quality.max_retries` extra seeds. Other lines are not regenerated.

If the line still does not fit at tempo 1.10, the runner tries `fit_retries.max_alternate_seeds` more seeds, then moves that line earlier into silence the previous line did not use, then asks the repair provider for a shorter faithful line. The repair reason is the record of what was compressed. Later lines are not moved. When the budget is spent, the line stays unplaced and the job is partial.

Voice assembly keeps up to `voice_edge.margin_lead_ms` and `margin_tail_ms` of the quiet audio Qwen already generated, and fades only that margin. The RMS 0.005 / 10 ms / pad 0 trim is still how duration is measured. The game bed is not faded, gated, or denoised. Phrase gain is clamped and applied only to the generated voice.

A line the fixed RMS gate would drop is kept only when a second look says the slice is quiet and harmonic. Near-silence, noise, and phrases such as “gracias por ver” stay dropped.

## Gates

`complete` requires every line placed, a reason on every unplaced line, quality on placed lines, voice edges, a continuous game bed (`mix - game - voice`), duration, sync windows, no clipping, one English track, and the same video bitstream. Anything else that is not a hard source/decode failure is `partial`.
