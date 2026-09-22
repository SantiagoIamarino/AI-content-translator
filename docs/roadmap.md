# Roadmap

## This version

- One local CLI, one job directory, file handoffs for translation and a single compact repair.
- Whisper Turbo transcription and energy-onset segmentation.
- Qwen3-TTS reference B, validated scheduler, game-only mix, partial exports.

## Not in this version

- Listening approval of the 18-minute clip in `docs/validation.md`. That export is partial, not a voice-quality approval.
- 1–2 hour recordings. The code does not load the video or synthesize the whole transcript at once, but that has not been timed or listened to.
- Automatic translation, a web UI, a database, or a queue.
- Word-level forced alignment.
- More than one compact rewrite, tempo above 1.10, or moving later lines.
- CosyVoice, WhisperX, pyVideoTrans, or another TTS model.
- Publishing, subtitles burned into the picture, or loudness normalization beyond the documented limiter.
