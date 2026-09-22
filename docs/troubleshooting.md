# Troubleshooting

## Resume

`bin/aidub status NAME` prints the state and the next command.

- `awaiting_translation` / `awaiting_repair`: write the response file. Do not rerun Whisper or Qwen by hand.
- `failed`: the manifest `error` field has the exception. Fix that cause and `bin/aidub resume NAME`. Completed stages with matching fingerprints are kept.
- `Job is locked`: another process holds `jobs/NAME/LOCK`. Wait for it. Delete `LOCK` only if no `aidub` process is running.

A crash mid-synthesis leaves finished cache files in `jobs/NAME/cache/synth/`. Resume reuses them.

## Paths with spaces

Pass the path as one argument. The runner does not use a shell.

```bash
bin/aidub init "/home/user/My Videos/clip.mp4" --name clip
```

## Wrong audio track

If the English voice replaced the game, or the mic was never transcribed, the ordinals are wrong. Do not reuse the job. `init` a new name with the correct `--mic-ordinal` and `--game-ordinal` after checking `ffprobe`.

## Partial dub

`english_PARTIAL.mp4` is playable. Unplaced ids and their English text are in `report/validation.md`. They are omitted from `english.srt` on purpose. Do not tempo them past 1.10 or shift later lines to hide the gap.

## Environment warnings

`SoX could not be found` and `flash-attn is not installed` come from the existing Qwen package. They do not fail the run. Do not install them from this project.

If CUDA is missing, the job fails closed. There is no CPU fallback.

## Protected files

The runner refuses to write into `/home/siamarino/ai-dubbing`. If validation says a protected hash changed, stop and do not "fix" it by rewriting the historical file.
