# Conversational continuity investigation — 2026-10-15

Work started from `297f406` on `quality-natural-dub`, with a clean working tree,
then moved to `fix/conversational-continuity-20261015`. The baseline is the actual
saved output and metadata, not a reconstruction from an older commit.

**No listening was performed by the agent.** Evidence consists of source and
candidate ASR, timelines, saved provider responses, waveform measurements,
intermediate WAVs and technical checks. Reduced silence is not listening approval.

## Baseline and reference

`minute-tranquila-corregida-20261014` is the latest successful corrected-reference
minute: 60.016667 seconds, seven retained/translated/placed cues, zero omissions,
zero repairs, presentation v2, four valid takes per cue. `minute-original-20261014`
is partial and uses the older reference. The corrected minute's reference note
still says “best-effort”; the approved matching pair and expected stripped-text
hash are the authoritative inputs used here. No reference file was edited.

| Protected input | SHA-256 |
| --- | --- |
| Relaxed reference WAV | `befb8b63e7bbaff92da9a6910cbce3fa147c9328503d9f6b5693274c556333bf` |
| Transcript file bytes | `f4829900c55d8c142153c3401c82036e89af388a959844f969568a2a9e829c3a` |
| Stripped UTF-8 transcript, as checked by aidub | `5961c35971055464ee01d61014b80501595720a3f63f34b24de436c14e07be88` |

Local evidence lives in ignored `runs/continuity-20261015/`. `baseline.json` records
HEAD and metadata hashes; `baseline/` contains unmodified job/config/transcript/
translation/schedule/report snapshots. The original snapshots still match every
recorded hash. Workstation paths and provider configuration remain local.

The longer job, `gameplay_oct13_quality`, is 4,364.967 seconds with 713 retained and
translated cues, 711 finally placed, two omitted, and a partial status. Its original
video path is unavailable, but extracted mic/game, cached takes, outputs and the
stream-copied Spanish comparison remain. Longer comparisons use these saved
artifacts and the older voice; they do not claim validation of the missing source
or approval of that reference. The original job remains partial.

## Traced examples

Times below are original recording times. Raw/processed takes, hashes, scores and
placement details are in each evidence directory's `evidence.json` and `cue_NNN/`.

| Interval | Source → target | Demonstrated loss and result |
| --- | --- | --- |
| Minute 22.18–33.36, cues 3–4 | “Pero luego no volví a jugarlo … El original / En Playstation 2 lo jugué bastante” → “But later I didn't go back to playing it. And back then, the original Resident Evil 4. / On Playstation 2, I played it quite a lot.” | Source ASR split 22.68–29.92 into four fragments; energy segmentation merged them. Cue 3's selected English core is 5.534 s within a 7.922 s source cue. It ends at 27.774 before the source's “El original” at 29.36–29.92. The words are already delivered earlier in English, not omitted by mixing. All cached acceptable alternatives are only 4.998–5.660 s. Cached-only changes leave this gap essentially unchanged; a newly generated take ends at 27.936. |
| Minute 34.30–38.49, cue 5 | “Así que bueno / La idea es jugarlo / Tranquilo” → “So, well, the idea is to play it in a relaxed way.” | Existing grouping already joins 0.214 s and 0.343 s source gaps. A valid 3.838 s take loses to a 2.946 s take under the old score. Source-duration scoring selects the longer cached take; placement ends 38.175 instead of 37.307, before the next fixed anchor at 38.492. No stretching or invented text. |
| Minute 45.16–56.44, cue 7 | “Pero bueno … así que vamos con un hardcore” → “But anyway, let's go with Hardcore … so let's go with Hardcore.” | Source ASR has four spans through 56.38; segmentation merges them. Both repetitions survive translation, with no review/repair rewrite. The chosen 7.617 s raw core scores zero pacing penalty, as do valid 8.345–9.162 s cores. Old scoring prefers seed 3049 for voice/pause proxies. The new soft duration term selects existing seed 49 (8.566 s); final end moves 52.837 → 53.786 at tempo 1.0. About 2.65 s of source-span tail still remains after the English end. |
| Minute 38.49–43.01, cue 6 | “… hardcore o estándar” → “… Hardcore or Standard.” | Seed 3048's raw file ends with last-10-ms RMS 0.00479. V2 retains the available 44.3 ms tail and fades its last 12 ms. The ending risk exists in raw generation; a longer fade cannot restore it. V3 rejects it as `raw_ending_unsettled`, a signal-based concern rather than a claim that a specific phoneme is missing. Cached-only replay chooses seed 48; full run chooses a newly verified seed 4048. |
| Longer 679.69–685.02, cue 64 | “… No debería luchar contra ninguno de estos” → “… ideally I shouldn't fight any of these.” | Same raw seed 106 and same text throughout. The core ends at raw 4.880917 s. A brief low-energy dip defeats the contiguous margin detector, which keeps 60 ms. Another 231.875 ms above RMS 0.0015 occurs beyond that cut, ending 347.583 ms after the core. V3 protects it and adds quiet fade room: end 684.566 → 684.874. The protected samples equal raw × gain; no fade attenuates them. This demonstrates removed generated signal, not a listening verdict about the exact final consonant. |
| Longer 649.96–655.02, cues 56–58 | “Ah, sí, ok / Ok / Eh” → “Ah, yeah, okay. / Okay. / Uh...” | All three reactions survive transcription, translation, synthesis and mixing. Core anchors stay fixed. The “Uh...” raw ending fails the new unsettled-edge check; another existing take is used. There is no evidence supporting microphone passthrough. |
| Longer 1928.560396, cue 302 | “Tenemos los cinco.” → “We've got all five.” | Scheduled and quality-passed, then omitted by the assembler. Cue 301 ends at 1928.552124667; rounded lead margin starts cue 302 at 1928.552104333, an overlap of 20.333 µs. Flooring the margin's sample budget yields a positive 21.333 µs gap. The original seeds 1343/344 now both survive the real mixer in `rounding-isolated/`. |
| Longer 2542.38, cue 427 | “¿Dónde cayó? ¿Dónde cayó?” → “Where'd it land? Where'd it land?” | ASR hears both repetitions in seeds 2469 onward. Normalization expands “Where'd” to “where would”; exact repetition comparison consequently calls the heard “where did” repetition unexpected. Correcting this contraction removes the false rejection. Cached seed 2469 is placed in `omission-427/`, with the current waveform/text checker rerun against its saved ASR. No fresh hearing or synthesis is claimed for that excerpt. |

The minute has **zero dropped transcription cues and zero failed/omitted synthesis
cues**. Its three uncovered energy portions are 10.179–10.220 (no speech heard),
21.866–22.180 (“Y...”, classified already transcribed), and 44.399–45.160 (“Y...”,
unintelligible). Their total is about 1.116 seconds. These classifications do not
prove silence or establish missing words. A second reading of cue 3 includes
“digamos”; that remains an unresolved alternative, not an automatic insertion.

The longer job has 18 dropped ASR entries and 111 reviewed energy gaps: 46
unintelligible, 44 no speech heard, 17 recovered, four already transcribed. In the
10:00–13:10 comparison, uncovered portions at 655.020–655.243 (“y”, probability
0.268), 779.969–780.015 (no speech heard), and 780.360–780.827 (“¡Gracias!”,
probability 0.576) remain uncertain. Keyboard sounds, breaths and speech cannot be
distinguished conclusively here. No missing words were inferred from energy.

## Changes and evaluated alternatives

`--preset continuity` includes the existing quality preset plus:

- A soft source-duration ranking term with a 10% tolerance, bounded by the existing
  natural-rate band. Text, voice consistency, internal-pause and tempo scores remain.
  Reactions under 1.6 seconds or four syllables get no duration penalty. It changes
  candidate choice; it never stretches audio to a target or moves later anchors.
- Presentation v3 inspects generated margins across RMS dips, protecting signal
  above RMS 0.0015 within 80 ms lead / 400 ms tail bounds. A 20 ms quiet allowance
  accommodates the existing 12 ms fade. Fades apply outside protected samples.
  Unsettled raw endpoints, exhausted tail bounds, and insufficient window space
  reject the take and consume a bounded alternate attempt. Tempo output that
  overruns the window is rejected, never sliced. A required validation gate records
  protected signal preservation and absence of window clipping.

Two demonstrated bug fixes also apply when resuming existing configurations:
lead-margin sample flooring in presentation v2, and the `where'd` text expansion.
The tests still reject an added third repetition or a missing second one.

Qwen generation, English ICL, reference pair, trim RMS 0.005 / 10 ms / pad 0 and
maximum tempo 1.10 are unchanged. All selected minute takes use tempo 1.0. Core
anchors are unchanged; margin starts may differ by tens of milliseconds.

Broader regrouping was evaluated but deferred: grouping already exists, and
joining minute cues 3–4 would exceed the configured ten-second unit bound.
The evidence does not establish that changing this bound preserves event timing
or improves delivery. Translation already keeps repeated reactions and discourse
markers in the key examples; no new translation or compression changes were made.
Quiet-speech thresholds were not relaxed without confirmed words. Nonverbal
microphone passthrough remains absent/disabled; no Spanish or keyboard audio was
mixed into the English voice.

## Verification and artifacts

| Comparison | Retained / translated | Before → after placed | New translation / synthesis |
| --- | --- | --- | --- |
| Corrected minute, cached replay | 7 / 7 | 7 → 7 | 0 / 0 |
| Corrected minute, full pipeline | 7 / 7 | 7 → 7 | 0 / 5 extra candidates, two selected |
| Longer 600–790 s, cached replay | 25 / 25 | 25 → 25 | 0 / 0 |
| Omission 302, 1926–1936 s | 4 / 4 | 3 → 4 | 0 / 0 |
| Omission 427, 2540–2554 s | 2 / 2 | 1 → 2 | 0 / 0; saved ASR rechecked |

The full minute first reused 30 raw takes and 30 verification records. Five extra
takes replaced ending failures in the best-of-four pools; fresh seeds 4045 and
4048 were selected for cues 3 and 6. Changing the contraction checker subsequently
invalidated verification identities correctly and reused all 35 synthesis WAVs.
The final full run is technically complete, has no open repairs, and passes the
required gates including copied picture, decode, headroom, PCM game identity,
quality, timing and protected endings. This is not listening approval.

Every cached comparison has zero PCM `mix-(game+actual voice)` error, copied-video
bitstream equality, clean decode and no decoded audio full-scale overshoot.
The longer excerpts validate the copied picture available locally, not the missing
original video. Stream-copy excerpt seeks can include keyframe preroll; the WAV
excerpts have exact requested sample boundaries.

- `after/jobs/minute-tranquila-corregida-20261014/output/english.mp4`: full final preview.
- `cached-minute/{before,after_cached}.mp4`: no new takes or translations.
- `cached-long-600-790/{before,after_cached}.mp4`: 3:10 gameplay comparison.
- `excerpts/`: 22–34, 34–44, 45–58 seconds of the minute; 649–656 and 678–686 seconds
  of the longer recording, with Spanish mic, before/after voice and copied video.
- `cached-*/cue_NNN/{raw,before,processed_same_take}.wav`: exact same-take processing
  comparisons. A rejected raw ending has no claimed successful processed file.
- `omission-{302,427}/`: recovered omissions and their evidence reports.
- `*/waveforms.png`: blue source mic, red before voice, green cached after voice.
- `index.html`: local listening index with timestamped comparisons.
- `final-tests.log`: 113 tests run: 112 passed, one existing recorded-shotgun fixture skipped
  because its reference/Deepseek cache is unavailable. Nine new regressions cover
  the demonstrated failures, bounded retry, onset/window protection and ranking.

Silence remains where English is naturally shorter, takes remain faster than the
Spanish source, or the source contains genuine pauses. Pacing and edge thresholds
are conservative measurable proxies; source ASR timing remains approximate.
The 400 ms protection bound cannot guarantee every possible soft ending. A full
long-job rerun and human evaluation of calm delivery remain outstanding limitations.

## Reproduction and resume

Use the checkout's launcher. On the investigated workstation the ignored local
config selects the isolated job root and the authorized existing interpreters:

```bash
bin/aidub --config config/continuity-after.local.json resume minute-tranquila-corregida-20261014
```

Repeated resume was checked: inspect/extract/transcribe/schedule/mix/validation
and risk report are reused after hashes are checked; no provider or synthesis call.
The experiment's job ID and provider handoff identities were deliberately retained
inside a separate jobs root. Its source ASR, timeline, translation request and
translation response are byte-identical to the original job.

To reproduce the cached experiment with an existing configured runtime:

```bash
AIDUB_PY=$(python3 -c 'import json; print(json.load(open("config/continuity-after.local.json"))["executables"]["python_qwen"])')
PYTHONPATH=. "$AIDUB_PY" scripts/continuity-evidence.py \
  --job jobs/minute-tranquila-corregida-20261014 \
  --output runs/continuity-20261015/cached-minute --end 60.016667
PYTHONPATH=. "$AIDUB_PY" scripts/continuity-evidence.py \
  --job jobs/gameplay_oct13_quality \
  --output runs/continuity-20261015/cached-long-600-790 --start 600 --end 790
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. "$AIDUB_PY" -m unittest discover -s tests -v
```

For a new configured job use `bin/aidub auto VIDEO --name NAME --mic-ordinal N
--game-ordinal N --mixed-ordinal N --preset continuity`, retaining the approved
reference config and recording-specific verified track mapping.

Existing snapshots do not acquire source pacing or v3 automatically. Scheduling
version 3 invalidates scheduling/mixing/validation for the margin bug; the changed
text checker invalidates candidate verification for sequence-checker jobs. Synthesis,
source transcription and provider response identities remain reusable. No jobs or
caches are deleted, no lock is bypassed, and all writes use the existing operation
lock. `continuity.py` also participates in opted-in schedule fingerprints.
