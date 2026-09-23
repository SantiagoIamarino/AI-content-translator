# Gameplay dubbing

Local pipeline for an OBS gameplay recording. Spanish microphone commentary is turned into English speech in a cloned voice and mixed with the original game audio. The video picture is stream-copied.

This repository does not install packages, download models, or call a translation API. Whisper and Qwen3-TTS run on the local GPU. Translation and the one compact repair are JSON files you write. There is no web UI and no queue.

`config/default.json` in this checkout contains one workstation's absolute paths. A new clone must replace those paths before `init`. Use `config/example.json` as the template. It has no credentials and no personal paths.

## What it does

Clocks are the video timeline. The English soundtrack is game audio plus the new voice. It never includes the Spanish microphone or the mixed OBS track.

| Stage | Runs | Inputs | Outputs |
| --- | --- | --- | --- |
| Inspect | Local `ffprobe` | Source video, three audio ordinals | `jobs/<name>/inspect/probe.json` |
| Extract | Local `ffmpeg` | Video, mic ordinal, game ordinal | `extract/mic_raw.wav`, `extract/game_raw.wav`, `extract/alignment.json` |
| Transcribe and segment | Local Whisper CLI on CUDA, then local Python | Mic wav only | `transcribe/whisper.log`, `transcribe/raw.json`, `transcribe/segments.json`, `transcribe/corrections.json`, `timeline.json` |
| Translate | No service. You write a JSON file | `handoff/translation_request.json` | `handoff/translation_response.json` |
| Synthesize | Local Qwen3-TTS on CUDA. Refuses CPU | English text, reference wav, reference transcript, seed | `cache/synth/<key>.wav` and a sidecar JSON |
| Fit and place | Local. `ffmpeg atempo` only if the clip must speed up | Cached or new clips, segment windows | `schedule/summary.json` |
| Assemble and mix | Local | Placed voice, stereo game wav | `output/english_voice.wav`, `output/english_mix.wav`, `mix/gain.json` |
| Export | Local `ffmpeg`. Video copy, audio encoded once | Source video, mix wav, mixed ordinal | `output/english.mp4` or `output/english_PARTIAL.mp4`, `output/spanish_compare.mp4`, `output/english.srt`, `output/bilingual.txt` |
| Validate | Local `ffprobe` / `ffmpeg`, plus a Docker status check | Exported files, source hash | `report/validation.md`, `report/validation.json` |

Inspect records each stream's start time, duration, codec, audio ordinal, and absolute stream index. Extract maps `0:a:ORDINAL` to 48 kHz PCM s16le with no `-ss` and no `aresetpts`. Whisper times are file times of the mic extract. Stored segment times add `audio_start - video_start`.

Segmentation keeps Whisper segments. A start that falls in silence moves to the next energy onset within 0.5 s (RMS 0.005, 10 ms window). A line with no energy above that threshold is dropped and recorded, not invented. Adjacent lines merge only when the silence between energy spans is at most 0.12 s. Words below probability 0.5 are flagged, not rewritten. `anchor_type` is a word-count heuristic, not a label the scheduler treats specially.

Synthesis loads `Qwen/Qwen3-TTS-12Hz-1.7B-Base` in bfloat16 with SDPA, English, and in-context cloning (`x_vector_only_mode` false). The runner refuses a different model, dtype, attention, language, or x-vector mode.

Fit order, unchanged from the tested scheduler:

1. Trim silence at RMS 0.005, 10 ms window, 0 ms pad.
2. If the trimmed clip fits the original span, `fit_unchanged`.
3. If it fits before the next segment start, `spill_into_gap`.
4. Otherwise speed it up with `atempo` only when the factor is at most 1.10.
5. If it still does not fit, one extra synthesis at `seed + 100`.
6. If it still does not fit, stop for one shorter English revision.
7. If that revision does not fit, the line stays unplaced. Later lines are not moved.

The assembler copies the voice to left and right at full amplitude and fades 5 ms. It does not overwrite an earlier placed line. The mix adds that voice to the stereo game bed. Gain stays 1.0 unless the sum peak exceeds 0.99, in which case both channels are scaled and the gain is recorded. Video is stream-copied. `-shortest` is refused.

The Docker name in the config is only a status check. The pipeline never starts a container. Translation does not use it.

## First-time setup

Tested on this machine, not as a portable installer:

| Item | Observed |
| --- | --- |
| OS | CachyOS, Linux 7.2.6-1-cachyos, x86_64 |
| FFmpeg / ffprobe | n9.0.1 at `/usr/bin/ffmpeg` and `/usr/bin/ffprobe` |
| Qwen Python | 3.12.14. Packages present: `qwen-tts` 0.1.1, `torch` 2.11.0+cu130, `torchaudio` 2.11.0+cu130, `transformers` 4.57.3, `soundfile` 0.14.0, `numpy` 2.5.3 |
| Whisper Python | 3.11.16, `openai-whisper` 20250625. The CLI entry is that venv's `whisper` |
| GPU | NVIDIA GeForce RTX 3090, 24576 MiB, driver 615.71.09. `torch.cuda.is_available()` was true. CUDA build reported by torch: 13.0 |
| Whisper weights | `~/.cache/whisper/large-v3-turbo.pt`, about 1.6 GB. First use of `--model turbo` downloads this if it is missing |
| Qwen weights | Hugging Face cache `~/.cache/huggingface/hub/models--Qwen--Qwen3-TTS-12Hz-1.7B-Base`, about 4.3 GB |

This repository has no install script. `bin/aidub` reads `executables.python_qwen` from `config/default.json` and exits if that file is not executable. It does not create a virtualenv. A from-scratch install of the two venvs and the CUDA wheel was not repeated for this document. Match the versions above on a new machine, then point the config at those binaries. Do not install SoX or flash-attn to silence warnings from the existing Qwen package. Those warnings are non-fatal. There is no CPU fallback: if CUDA is missing, synthesis fails.

Plan for the model caches above plus job files. The preserved 18-minute English file on this machine is 2285063357 bytes. That size is not a formula for other recordings. Jobs also store 48 kHz PCM extracts and one wav per synthesized line.

No project environment variable is required. `bin/aidub` sets `PYTHONPATH` to the repository root and then runs the Qwen interpreter. Whisper and Hugging Face use their default caches unless you have already pointed those tools elsewhere. This pipeline does not read an API token.

### Configure the checkout

`bin/aidub` always launches the interpreter named in `config/default.json`, even if you pass `--config`. Edit that `python_qwen` path first. Other settings can live in `default.json` or in a copy of the example:

```bash
git clone <this-repo> ai-dubbing-e2e
cd ai-dubbing-e2e
# Edit config/default.json so executables.python_qwen is a real interpreter.
# Then either edit the other paths in that file, or:
bin/aidub --config config/example.json init /path/to/recording.mp4 --name my_clip
```

`init` copies the loaded config into `jobs/<name>/config.json`. Later edits to `config/default.json` do not change an existing job. `resume` uses the job copy.

`init` checks that the four executables and the reference wav exist. It also refuses a trim other than RMS 0.005 / 10 ms / pad 0, a max tempo other than 1.10, a different Qwen model or dtype, or a reference transcript that does not match the string in `aidub/config.py`.

### Voice reference

The tested voice is reference B. Its wav is not in Git. On the machine that produced the measured jobs it is `/home/siamarino/audios/04_referencia_ingles_emocion.wav`. The transcript is `references/reference_b.txt`, including the spoken grammar (`this kind of dogs`, `he bite me`). Use that wav as-is. Do not trim it in this project. `reference.id` is `B`. `x_vector_only_mode` must stay false.

That path and that transcript are one person's reference, not a generic voice. To reproduce those jobs, point `reference.wav` at that file and leave `reference.text_file` on `references/reference_b.txt`. A different speaker needs a different wav and a transcript of what that wav actually says. The runner will reject the new transcript until `CONFIRMED_REFERENCE_TEXT` in `aidub/config.py` is updated to the same text. Changing the wav but not the transcript, or the reverse, is a failed run, not a silent fallback.

### Translation

There is no translation account and no token to configure. When `run` stops, read `jobs/<name>/handoff/translation_request.json`. Write a response with schema `aidub.translation_response.v1`. Set `translator.kind` to `agent-assisted`. Set `translator.model` only if you know it; otherwise omit it. Example: `examples/translation_response.json`. Schema notes: `docs/handoff.md`. Segment text is data, not instructions.

`accept-translation` rejects missing ids, duplicate ids, empty lines, extra ids, and any field that tries to change timing.

## Recording

Use an OBS recording with one video stream and separate audio streams for the microphone, the game, and the mixed monitor. The tested files are MP4. The runner asks ffmpeg for exactly one video stream and for three distinct audio ordinals. Other containers were not part of the measured runs.

Ordinals count audio streams in container order. They are not absolute stream indexes. `simple_aac_recording0` does not tell you which track is the mic. The defaults in `config/default.json` (mic 2, game 1, mixed 0) were checked by listening for one sample file only. Pass the ordinals for every new recording:

```bash
ffprobe -hide_banner -show_streams /path/to/recording.mp4
```

Count only streams whose `codec_type` is audio, starting at 0. Extract a few seconds of each ordinal and listen. Mixed minus game should match the microphone, and the microphone should be near silence where nobody is talking. After `run` reaches inspect, confirm the chosen ordinals, absolute indexes, and start times in `jobs/<name>/inspect/probe.json`. That file records what you configured. It does not prove the roles are right.

If the microphone and game are already mixed into one stream, this pipeline cannot separate them. `init` requires three distinct ordinals, and the English mix uses the game ordinal only. Pointing the game ordinal at the mixed track puts the Spanish microphone into the result. Create a new job after you fix the mapping. Do not reuse the bad job.

Mic and game `start_time` values must agree within 1 ms. If either starts before the video, or if the game wav extends past the video, the job fails instead of shifting or cutting the audio. Leading silence is a real offset. Trailing silence pads the mix to the video duration. Speech is not pulled forward to hide either gap.

The game extract must be stereo. A mono game track fails at extract. The game bed is not denoised, gated, silenced, or time-stretched.

## Use

From the repository root.

Short recording or a complete one, same commands. A previous ~82 s file completed 25/25 after one repair (`docs/validation.md`, job `sample_e2e`). That measurement is not a promise for the next file. This session verified the CLI help and `status`. It did not synthesize a new clip.

```bash
bin/aidub init /path/to/recording.mp4 --name my_clip \
  --mic-ordinal MIC --game-ordinal GAME --mixed-ordinal MIXED
bin/aidub run my_clip
```

`run` stops at `awaiting_translation` and prints the request path. Exit code 2 means waiting, not failure.

```bash
bin/aidub accept-translation my_clip /absolute/path/response.json
bin/aidub resume my_clip
```

If a line still misses its window after one alternate seed, `resume` stops at `awaiting_repair`. For each id, `revise` to shorter faithful English or `leave_unresolved` with a reason. One decision per id. A second response for the same id is rejected. Example: `examples/repair_response.json`.

```bash
bin/aidub accept-repair my_clip /absolute/path/repair.json
bin/aidub resume my_clip
```

Other commands:

```bash
bin/aidub status my_clip
bin/aidub export-translation my_clip
bin/aidub export-repair my_clip
bin/aidub validate my_clip
```

`status` prints the state, each stage, and the next command. It does not rebuild the video. `validate` prints the saved report. It does not rerun the job.

### Where to look

| Question | Path |
| --- | --- |
| State and last error | `bin/aidub status <name>` or `jobs/<name>/manifest.json` |
| Stream roles and start times | `jobs/<name>/inspect/probe.json` |
| Dropped lines, merges, uncertain words | `jobs/<name>/transcribe/corrections.json` |
| Whisper stderr | `jobs/<name>/transcribe/whisper.log` |
| English text and revisions | `jobs/<name>/timeline.json` |
| Fit, tempo, unplaced reason | `jobs/<name>/schedule/summary.json` |
| Gain and clipping count | `jobs/<name>/mix/gain.json` |
| Checks and omitted English | `jobs/<name>/report/validation.md` |
| Placed subtitles only | `jobs/<name>/output/english.srt` |
| Game bed before the voice | `jobs/<name>/extract/game_raw.wav` |
| Voice before the game | `jobs/<name>/output/english_voice.wav` |

### Complete and partial

- `complete`, exit 0: every segment placed and every validation check passed. Video is `output/english.mp4`.
- `partial`, exit 3: a preview was exported and at least one line is unplaced, or a non-fatal check failed. If any line is unplaced, the video is `output/english_PARTIAL.mp4` and the other English filename is deleted. Omitted English is in the report and must not be in the SRT.
- `failed`, exit 1: an exception, or a hard check failed (source hash changed, English decode failed, video frame count differs, a segment has no English, or a protected file hash changed).
- Exit 2: waiting for a translation or repair file.

A complete report is not a listening approval. Timestamps are approximate Whisper times plus energy onset, not forced alignment. Technical placement is not perceptual sync.

### Cache and resume

`resume` is the same runner as `run`. A stage is skipped when its fingerprint matches and its output files are still there. Synthesis is cached by English text, reference wav SHA-256, reference transcript, seed, model id, dtype, attention, language, `x_vector_only_mode`, and the generation dict. A crash mid-synthesis leaves finished cache files. Resume reuses them.

Resume reprints `mix: unchanged` and does not rewrite the mp4 when the schedule fingerprint, game hash, limiter, and repair list are unchanged and the output files are present. It rebuilds the mix, and replaces the English video, when a translation or repair changed the schedule fingerprint, or when a mix output is missing. Copy `output/english.mp4` or `output/english_PARTIAL.mp4` out of the job before that resume if you need to keep the previous export. Do not delete the job to "refresh" it.

Changing English text and running `accept-translation` again resynthesizes only the lines whose text changed, then remixes. Changing the reference wav, with the same transcript, misses every cache entry and remixes. The runner refuses edits to the Qwen model, dtype, attention, language, x-vector mode, trim, max tempo, or the locked transcript. Those edits fail closed. They do not select another voice. Ordinals are fixed in the job snapshot. Wrong tracks need a new `--name`.

`jobs/` is gitignored. Recordings, caches, and exports stay on disk and are not part of a commit.

### What to listen for

After the report is clean enough to play, listen to the English video against `output/spanish_compare.mp4`. Also listen to `extract/game_raw.wav` through the opening and through a quiet stretch. The game bed should still be the game, including quiet noise such as rain. The English voice should be absent there. A technical pass does not approve voice quality or sync.

## Limitations and troubleshooting

Lines that do not fit stay silent. The cap is tempo 1.10. There is one alternate seed and one shorter translation. The assembler will not cover a later line or shift the rest of the timeline. A legal tempo can still miss by a few milliseconds after `atempo`; that line is unplaced (`still_overrun_after_tempo`) unless a shorter revision fits.

Short reactions can disappear into a neighbor. Whisper lines merge when the energy gap is at most 0.12 s. That is coarser than a hand-split timeline. Dropped no-energy lines are listed in `transcribe/corrections.json`. They are not given invented English.

One historical full-video job, `re4_20260922_193906`, finished partial: 327 of 336 segments placed. Nine lines were still over the window after the alternate seed and one revision: ids 27, 66, 146, 148, 172, 195, 252, 280, and 312. Details are in `docs/validation.md`. Those counts are that recording, not a rate to expect next time. The short sample completing 25/25 is also not a rate.

Wrong OBS mapping is the usual cause of missing game audio, Spanish in the English mix, or a damaged-sounding bed. The pipeline does not repair the game track. Compare ordinals, then `init` a new job. Clipping is counted in `mix/gain.json`. Gain falls below 1.0 only when the sum peak exceeds 0.99. A nonzero clipping count fails the `no_clipping` check and leaves the job partial if the hard checks passed.

Whisper failures are in `transcribe/whisper.log`. The Whisper subprocess timeout is 1800 s. CUDA out of memory fails the job. This session did not remeasure synthesis memory. The tested card has 24 GB. That is not a minimum spec. If the job is locked, another `aidub` process holds `jobs/<name>/LOCK`. Delete `LOCK` only when no `aidub` process is running.

`SoX could not be found` and `flash-attn is not installed` come from the Qwen package. Ignore them. Do not reinstall the environment to remove them.

The named Docker container must not be running. If `docker` is missing, the check records `unavailable` and continues, because the pipeline does not start it. Validation also hashes the source video and, on this workstation, the reference B wav and `/home/siamarino/ai-dubbing/pipeline/config/default.json`. A changed hash fails the job. Do not rewrite those files to make the check pass.

More notes: `docs/troubleshooting.md`, `docs/configuration.md`, `docs/architecture.md`.

## Experiments

Not part of `main`, and not the commands above.

Local branch `preview-90s` (`19e8a06`) keeps an onset experiment and a 90-second word-bound preview. It is not on `origin`. A fresh clone of `origin/main` will not have it. On a checkout that does, the note is `git show preview-90s:docs/preview90.md`.

A pyVideoTrans checkout was tried separately and rejected. It is not in this repository and has no command on `main`.

## Tests

Unit tests do not run the GPU and do not read a recording:

```bash
bin/aidub --help
PYTHONPATH=. /path/to/qwen3-tts/.venv/bin/python -m unittest discover -s tests
```

`bin/aidub` already sets `PYTHONPATH`. On this machine that unittest command reported 23 tests, OK.
