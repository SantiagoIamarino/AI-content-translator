# Gameplay dubbing

Local pipeline for an OBS gameplay recording: Spanish microphone commentary becomes an English dub in the same voice, mixed with the original game audio.

This is agent-operated. Whisper and Qwen3-TTS run locally. Translation is a file handoff to the coding agent already in the session. There is no paid API and no local translation LLM.

## Quick start

```bash
bin/aidub init /path/to/recording.mp4 --name my_clip
bin/aidub run my_clip
```

`run` stops at `awaiting_translation` and writes `jobs/my_clip/handoff/translation_request.json`. The agent writes a response, then:

```bash
bin/aidub accept-translation my_clip /path/to/response.json
bin/aidub resume my_clip
```

If a line does not fit, `resume` stops at `awaiting_repair`. Same pattern with `accept-repair`. See `AGENTS.md`.

Check status any time:

```bash
bin/aidub status my_clip
bin/aidub validate my_clip
```

`bin/aidub` uses the existing Qwen virtualenv from `config/default.json`. It does not install packages.

## Outputs

Inside `jobs/<name>/output/`:

- `english.mp4` or `english_PARTIAL.mp4` — gameplay video, game-only audio, English voice. English is the only, default audio track.
- `spanish_compare.mp4` — same video with the original mixed track (game + Spanish mic).
- `english_voice.wav`, `english_mix.wav`
- `english.srt` — placed lines only
- `bilingual.txt`

The report is `jobs/<name>/report/validation.md`.

## Exit codes

- `0` complete
- `2` waiting for a translation or repair file (not a failure)
- `3` partial preview exported
- `1` failed

## Limits

Timestamps are approximate. A complete status means every segment was placed under the scheduler rules. It is not a listening approval. `sample.mp4` does not prove a 1–2 hour recording. One later 18-minute clip is recorded in `docs/validation.md` as a partial export, not as general acceptance.

SoX and flash-attn warnings from the existing Qwen install are non-fatal. Do not reinstall environments to silence them.
