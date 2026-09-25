# Unattended run on base-video.mp4

Branch `unattended`, worktree `/home/siamarino/ai-dubbing-e2e-unattended`. `main` stayed at `7e9b828`.

Input `/home/siamarino/vids-sample/base-video.mp4`: 81.716667 s, 1920×1080, 60 fps, 4903 frames. Audio ordinals rechecked on this file: mixed 0, game 1, mic 2. `(mixed − game)` correlates 0.9983 with the mic. The opening 2.8 s is near-silent on the mic and audible on the game.

English video: `jobs/base_unattended/output/english.mp4`. Status `complete`, 25/25 placed, 22/22 checks passed. This is not a listening approval.

## What the first command did

`bin/aidub auto` called the configured command provider (`cursor-agent` in ask mode, no API key in the repo). Translation took 85.4 s (25 lines). Repair took 121.5 s (id 20). Nobody wrote the JSON by hand.

That first invocation exited 3. A speaker check was treating ordinary clones as the wrong voice because it counted two brightness measures as independent, and the Whisper worker's first non-JSON line aborted transcription. Six lines were left out. After the checker was changed so a rejection needs both pitch and voiced brightness, and the worker ignores non-JSON chatter, `bin/aidub resume` placed 25/25 from the existing cache (25 hits, 0 new quality retries) and the gates passed.

## Id 20

Spanish: `Estamos dentro Estamos dentro de la iglesia Vamos, vamos`. The provider shortened it to `We're inside the church. Let's go, let's go.` Reason recorded: the first "We're inside" was dropped because "We're inside the church" already says it; the church and the repeated "let's go" stayed. It then fit without tempo.

## Edges

Qwen's own files already have a quiet lead (about 44–133 ms on the lines that were measured) and a long low tail. The previous assembler deleted that with the RMS 0.005 / pad 0 trim and then faded the remaining speech for 5 ms. The game bed was not the thing being cut: `mix − game − voice` was about one PCM step.

This run keeps up to 20 ms of that lead and 60 ms of the tail, fades only the margin, and loudness-matches the voice. Excerpts, same generated take:

- `runs/unattended/excerpts/id01_before_trim_fade5ms.wav` and `id01_after_margin.wav` (and the same pair for ids 7, 17, 22)
- `idNN_placed_voice.wav`, `idNN_placed_mix.wav`, `idNN_game_bed.wav` are the same timestamps in the finished mix

Id 1: trimmed-and-faded 1.876 s, margin version 1.956 s, 3192 raw samples of lead had been removed. Bed error on that slice: 0.
