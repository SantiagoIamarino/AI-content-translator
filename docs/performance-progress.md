# Conversational performance implementation

Baseline: `f82d286` on the existing isolated development branch. The read-only
audit and the user's listening observation near 00:10 are the evidence base.
Local artifacts live under ignored `runs/performance-20261015/`.
No listening by the agent is claimed. Technical status is not perceptual approval.

## Stage 1 — duplicate filtering and surviving coverage

Completed: a head-repeat match cannot delete the later cue's unique suffix.
When the complete later phrase is heard once in its own interval, the earlier
short duplicate is removed instead. An ambiguous reading preserves both cues.
Energy coverage is rebuilt against surviving cues before gap recovery, and the
final uncovered intervals are recorded after recovery. Existing raw Whisper
windows and matching second-hearing files remain reusable. The second-pass
stage version invalidates dependent transcription/translation artifacts; original
jobs are not modified during implementation.

Changed files: `aidub/second_pass.py`, `aidub/segment.py`, `aidub/pipeline.py`,
`tests/test_performance.py`, this note. Evidence: longer recording 44:11.66–44:13.22,
“A ver este candado”; both saved hearings contain the unique words.

Verification: 116 tests, 115 passed, one existing recorded fixture skipped.
The first test run exposed an incorrectly constructed single-token duplicate
fixture; the fixture now exercises the configured two-token minimum.
Log: `runs/performance-20261015/stage1-tests.log`.

## Stage 2 — timed source-event representation

Completed: opt-in `performance` preset and a microphone-hash-bound event ledger.
Confirmed listening annotations can separate a hesitation from broad lexical-cue
coverage, preserving the lexical cue ID and words. Internal events can split a cue
only when all original words can be reconciled and none overlap the event.
Source-ASR isolated hesitations retain their own evidence. Acoustic periodicity
only nominates uncertain regions; it never creates a speakable event. Noise,
breaths and silence cannot insert English. Laugh/sigh synthesis and passthrough
remain unvalidated and unresolved. Translation/review receive event evidence,
preserve conversational function, and cannot replace a fixed realization with
arbitrary words. Filler-only candidate verification now detects missing events
and added speech. A required placement gate keeps unresolved events partial.

Changed files: `aidub/events.py`, `aidub/pipeline.py`, `aidub/context.py`,
`aidub/review.py`, `aidub/handoff.py`, `aidub/textnorm.py`,
`config/presets/performance.json`, `tests/test_performance.py`, this note.
Verification: 120 tests, 119 passed, one existing fixture skipped.
Log: `runs/performance-20261015/stage2-tests.log`. No provider or TTS call yet.

## Stage 3 — source pauses, reaction boundaries and complete tail analysis

Completed: bounded per-cue microphone pause evidence; contextual candidate
evaluation can resolve only a pause rejection supported by a source pause at a
similar relative position and duration. Other quality failures remain. Selection
penalizes unsupported take pauses and missing source pauses. The opt-in source
duration target can follow the source span within the existing hard rate bound;
it never stretches audio or moves later anchors. Isolated reactions are protected
from short-pause joining and from unrelated utterance groups. This does not blindly
expand synthesis unit sizes. Source pauses and event evidence reach translation.

The performance preset inspects the entire generated tail within a two-second
analysis bound, protects quiet decay down to RMS 0.0001, fades outside it and
rejects unpreservable windows. The established trim measurement stays unchanged.
Processed endpoints are checked; tempo-processed candidates require their own
saved ASR verification. Raw truncation still requires another take.

Changed files: `aidub/performance.py`, `aidub/pipeline.py`, `aidub/linework.py`,
`aidub/continuity.py`, `aidub/context.py`, `config/presets/performance.json`,
`tests/test_performance.py`, this note. Verification: 123 tests, 122 passed,
one existing fixture skipped. Log: `runs/performance-20261015/stage3-tests.log`.

## Stage 4 — recoverable evaluation and honest uncertainty status

Completed: `scripts/performance-evaluate.py` prepares isolated bounded source
fixtures from saved mic/game and copied picture, freezes the approved reference
configuration, renders Spanish/prior/new comparisons, and runs a serial resumable
queue through this checkout's `bin/aidub`. Each job holds its normal provider lock;
the queue has a separate owned lock. Saved receipts prevent accidental reuse for
another source interval. Fixture picture bitstreams are checked after mux.
The first fixture attempt caught a final `-t` dropping copied packets; the mux now
preserves every packet of the already-bounded picture. No source job was changed.

The cached evidence tool accepts `--preset performance`, applying current checks
to saved ASR and raw takes with no fresh hearing/synthesis. Minute: 7/7 placed;
600–790-second passage: 25/25 placed. Both have zero PCM game-bed error and copied
video identity. These comparisons exclude event recovery and new translations;
the long cached comparison retains its historical voice. Same-take WAVs remain
separate from reselection results.

Performance jobs now remain partial with unintelligible source gaps or disputed /
unconfirmed bilingual reviews. Reports expose the spans and texts. Validation-only
version 5 reuses source analysis, provider responses and synthesis. This is stricter
than the old reviewed-gap gate, without treating noise as missing speech.

Changed files: `scripts/performance-evaluate.py`, `scripts/continuity-evidence.py`,
`aidub/pipeline.py`, `tests/test_performance.py`, this note. Verification: 124 tests,
123 passed and one existing fixture skipped. Log: `stage4-tests.log` in local runs.

Evaluation currently running (not yet accepted): first-minute job under
`runs/performance-20261015/jobs/minute-tranquila-corregida-20261014` using
`config/performance-eval.local.json`. New 00:10 event is `thinking-0010`,
10.178979–10.720000, user listening provenance, approximate boundaries; no original
microphone passthrough. The serial queue waits for that job and then runs the eight
prepared audit passages plus the minute comparison. Logs: `minute-run.log`,
`queue.log`, `queue/state.json`, individual passage `run.log` and `comparison.json`.

Exact next step after an interruption: inspect those logs and manifests before
starting anything. If the queue is still alive, let it continue. If inactive,
resume the minute with `bin/aidub --config config/performance-eval.local.json auto`
using its original saved source path and name; then run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. /path/to/authorized/python \
  scripts/performance-evaluate.py run-set --output runs/performance-20261015
```

The local config records the already-authorized interpreter; no installation is
needed. If a passage fails, preserve its request/response state, diagnose and resume.
Do not regenerate matching saved provider responses or raw takes. Once finished,
review exact text/event deltas and omissions, render short 00:09–00:13 listening
excerpts and a top-level comparison index, verify repeat resume, record reference
hashes and technical checks, update documentation/results and commit. No listening
or perceptual approval is claimed.

## Stage 5 — observed fitting failures and connected hesitation realization

Completed after the first real synthesis run: four valid standalone `Uh...` takes
did not fit the provisional 0.541021-second window, but best-of-N stopped before
trying its remaining fit budget. The opt-in `search_for_placeable` now uses the
remaining bounded attempts when no valid take is placeable. Events cannot borrow
earlier silence through a leading shift or request a meaningless compact rewrite.
A regression covers successful extra fit search and exhausted-budget partial status.

All eight standalone takes still failed that narrow provisional window. That
attempt is preserved under `standalone-attempt/`, including its preview, voice,
schedule and failed event gate. The event's identity and source timestamps remain
unchanged. The performance preset now realizes a leading annotated hesitation as
a required prefix of its connected lexical thought, retaining the original lexical
cue ID and source onset. Its estimated internal lexical onset remains evidence,
not a hard deadline imposed on an isolated filler take. Translation/review require
the prefix, generated ASR must hear it, and event coverage requires that check.
This avoids deleting the event, cutting its decay or moving it earlier to fit.

The PCM source fixtures now explicitly export MKV, as required for a copied PCM
Spanish comparison track. The first queue's refused MP4 exports remain in logs;
no compatibility gate was disabled. A legacy review prompt retains its original
bytes when the new delivery policy is absent.

Changed files: event/context/review/handoff/performance/linework/pipeline modules,
performance preset, evaluation script, focused tests, README/configuration docs,
new `docs/performance.md` and this note. Verification: 126 tests, 125 passed, one
existing fixture skipped (`stage5-tests.log`). No reference/generation parameter
was changed.

Exact next step: the second serial queue is running with the minute first; inspect
`queue-second.log` and each passage's `run.log`. Resume with the command from Stage 4
plus `--first minute-tranquila-corregida-20261014` if inactive. Current source-event
mode is `prefix_with_following`. All configs are already migrated under owned locks;
do not reset them or repeat completed providers/synthesis. Inspect the resulting
event verification and contextual previews, address demonstrated failures without
weakening gates, then finish the final evidence/results and resume verification.

## Stage 6 — processed event verification and material source conflicts

Completed: required hesitation prefixes are checked in the processed candidate,
with an independent saved waveform/ASR verification identity. A required gate
records this, separately from raw-prefix evidence. Schedule versioning invalidates
only fitting/processing for this change; matching translations and raw synthesis
remain reusable. Validation version 6 records the new gate.

The demonstrated longer-job polarity disagreement (“ya es suficiente” versus
“aún no es suficiente”) is no longer eligible for an unattended spoken guess.
Opposite negation readings of shared content are marked as material conflicts and
remain unvoiced/partial pending source resolution. This conservative rule is
limited to detectable polarity conflicts; it does not claim general semantic ASR
adjudication. Minor first-minute `volví/volvía, digamos` disagreement remains
available to review. The summary tool records exact text/event differences,
counts, settings, failed gates and preview links without changing job state.

Changed files: `aidub/fidelity.py`, events/context/review/performance/pipeline
integration, evaluation summary tooling, tests and docs. Verification: 127 tests,
126 passed, one existing fixture skipped (`stage6-tests.log`). All 20 original
metadata hashes still match; all nine evaluation configs preserve the approved
reference, Qwen and schedule blocks (`preservation.json`).

Exact next step: let `queue-second.log` continue. The connected minute is in
configured provider review; prepared long jobs follow serially. Because the minute
worker began before the processed-prefix gate was added, resume it once after its
current worker exits to exercise that new gate using caches. Do not repeat paid
provider calls: matching requests/responses are retained. Render/summarize the
finished passages, diagnose source-negative fixtures honestly, and finish the
timestamped excerpts, final resume check, results docs and commit.

## Stage 7 — timed connector coverage

Completed: neighboring text alone can no longer close a gap when its matching
word occurs several seconds away. Source word timestamps now survive initial
segmentation; the gap check requires a nearby matching word. The first minute's
21.86-second `Y...` reading remains uncertain rather than falsely covered by a
later `Y` in a long cue. No English conjunction is invented from that reading.
Coverage is refreshed after final joining and event realization, including the
00:10 prefix interval. Reported uncovered span duration is explicitly not a
measurement of missing speech. New segmentation version 3 reuses saved raw ASR
and matching second hearings, invalidating their interpretation and dependents.

Changed files: `aidub/segment.py`, `aidub/second_pass.py`, `aidub/pipeline.py`,
`tests/test_performance.py`, this note. Verification: 129 tests, 128 passed,
one existing fixture skipped (`stage7-tests.log`).

Exact next step: the connected minute has reached synthesis (translation includes
`Uh... This is the first time...`). Let the second queue continue. After its minute
worker exits, resume that minute once under the current code so segmentation 3,
processed-prefix verification and material-conflict gates are exercised. Expect
cached provider reuse and raw-take reuse for identical texts. Keep the recovered
hesitation's approximate timing explicit. The remaining long passages will start
with current code. Finish previews, source/target/event accounting, operational
resume evidence and final documentation when the queue completes.
