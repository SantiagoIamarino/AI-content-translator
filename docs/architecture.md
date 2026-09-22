# Architecture

## Stages

```
inspect → extract → transcribe → translation handoff
        → synthesize/schedule → repair handoff (only if needed)
        → mix/mux → validate
```

States: `pending`, `running`, `awaiting_translation`, `awaiting_repair`, `failed`, `partial`, `complete`.

A job is a directory under `jobs/` with `manifest.json`, a config snapshot, and stage outputs. Writes outside that directory are refused. The historical tree `/home/siamarino/ai-dubbing` is read-only.

`manifest.json` is replaced atomically. A `LOCK` file uses `flock` so two runs cannot update the same job.

## Timing

Clocks are the video timeline.

- Probe records each stream's `start_time`, duration, time base, and both the audio ordinal and the absolute stream index.
- Extract uses `ffmpeg -map 0:a:ORDINAL` with no `-ss` and no `aresetpts`.
- Whisper times are file times of the raw mic extract. Stored segment times add `audio_start - video_start`.
- If mic and game starts differ by more than 1 ms, the job fails instead of shifting one of them.
- Leading silence is real offset. Trailing silence pads the mix to the video duration. Speech is not pulled forward to hide either gap.
- Safe window is segment start → next segment start. The last window ends at the video duration, not the shorter audio-stream duration.
- Placement does not move later lines to make room.

## Speech fit

Ported qwen-full rules (`PROVENANCE.md`):

1. Trim silence at RMS 0.005, 10 ms mean-square window, 0 ms pad.
2. If the trimmed line fits in the original Whisper span, status is `fit_unchanged`.
3. If it fits before the next start, status is `spill_into_gap`.
4. Otherwise apply `atempo` only when the required factor is ≤ 1.10.
5. If it still does not fit, one extra synthesis at `seed + 100`.
6. If it still does not fit, stop for one compact-translation repair.
7. If that regeneration does not fit, the line stays unplaced.

The assembler never overwrites an earlier placed line. A 1–2 sample grid trim only removes rounding error at a boundary.

## Cache

Key: English text, reference wav SHA-256, reference transcript, seed, model id, dtype, attention, language, `x_vector_only_mode`, generation settings.

A cache hit is not a fresh synthesis. Resume of a finished job does not load Qwen again.

## Mix

Game stays stereo. The voice is copied to left and right at full amplitude (not divided by sqrt(2)), matching the validated sample mix. Gain stays 1.0 unless the sum peak exceeds 0.99, in which case both channels are scaled and the gain is recorded. The English soundtrack never includes the Spanish mic or the mixed OBS track.

Video is stream-copied. `-shortest` is not used.

## What a short sample does not prove

Segment synthesis avoids loading the video and avoids speaking the whole transcript as one utterance. That is the shape required for longer recordings. It has been executed on an ~82 second file only.
