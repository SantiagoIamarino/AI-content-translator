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

## Stage 8 — demonstrated ASR normalization of generated fillers

Completed after actual generation: every long-sentence ASR reading omitted the
requested `Uh`, so the initial prefix check rejected the whole sentence. Focused
CPU Whisper hearings of existing seeds 1044 and 5044 at 0.55, 0.8 and 1.1 seconds
all return `Uh` (the longest seed-1044 reading says `Uh, this is`). This demonstrates
that absence from full-sentence ASR was an unsuitable proxy, rather than evidence
that these raw takes lack the filler. No listening or fresh TTS was used for this
finding. Evidence: `prefix-probe/results.json` and exact cropped WAVs.

New `aidub/vocal_verification.py` checks distinct short windows without an expected
text prompt, requires concordant prefix readings, retains probabilities/low
confidence, and caches by waveform, checker implementation and ASR identity.
Raw and processed takes each receive this evidence. ASR fallback identities cannot
share successful checks across a runtime change. Risk reports flag recovered
prefixes and low-confidence focused readings. Material-polarity comparison also
uses the closest original source part, avoiding an unrelated negation in another
joined clause.

Verification: 130 tests, 129 passed, one existing fixture skipped
(`stage8-tests.log`). Tests include cache reuse, missing-prefix rejection,
concordant low-confidence readings and joined-clause polarity scope.

Exact next step: `minute-prefix-verification.log` is running the updated minute
with this checkout's CLI, reusing matching provider responses and raw takes.
The second queue continues the other passages independently; check `queue-second.log`
and their manifests. Do not restart active jobs. After the minute finishes, inspect
the event's raw/processed verification, rerender its comparison, then repeat resume
to prove no new provider/synthesis work. Finish remaining passage diagnostics,
timestamped excerpts, summary index, final evidence docs and commit.

## Stage 9 — passage-discovered uncertainty and protected-lead failures

Completed: the actual passage queue exposed `protected_edge_outside_window` for
settled takes as short as 5.024 seconds in a 6.394-second window. The preceding
take ended within one sample of this source anchor, so there was no leading
margin budget. Performance presentation can now delay the core locally by its
required lead (at most 80 ms), preserving all protected audio and the fixed next
anchor. It still rejects insufficient room and raw truncation.

Quiet fixtures also demonstrated that a text reviewer could mark an acoustic
reading disputed while the pipeline still voiced its plausible English. Such
disputed/unconfirmed lines now remain explicitly unplaced under the performance
policy, retaining text, evidence and partial status. This also avoids loading TTS
for an entirely withheld passage. New energy-gap words require a second timed
reading with neighboring acoustic context: the repetition passage's isolated
`¡Gracias!` had a 20-ms word timestamp despite probability 0.65. Its status is not
assumed to be speech; the next run will record its contextual corroboration.

Changed files: fidelity, pipeline, second-pass interpretation, performance preset,
regression tests and docs. Verification: 133 tests, 132 passed, one existing
recorded-fixture skip (`stage9-tests.log`). Matching acoustic hearing caches keep
their identities; provider and generation keys remain unchanged for identical
requests and takes.

Exact next step: apply the two new performance policy settings only to the nine
stopped experimental config snapshots/local configs, preserving approved reference,
Qwen and schedule blocks. Resume `scripts/performance-evaluate.py run-set` serially
with the saved receipts. It must reuse original raw ASR/hearings and saved provider
responses for matching requests; changed gap content legitimately needs its own
translation response. Inspect actual contextual confirmation, local onset delay,
omissions and fresh/cache counts. Finish excerpts, summary, idempotent resume and
final results documentation after that queue exits.

## Stage 10 — fair source-timing confirmation and comparison picture origin

Completed: actual context confirmation of `Intentar...` used a broad Whisper word
interval (104.224–105.464 local seconds). Its midpoint was earlier than the
105.024–105.340 uncovered span, even though the word interval covers that span.
The confirmation now requires meaningful overlap rather than treating approximate
Whisper midpoints as exact alignment. Recovered text still needs concordance and
the configured confidence floors. Interpretation version 4 reuses both hearings.

The picture comparison harness also had a demonstrated seek error: a packet hash
identifies the 600-second Matroska fixture's first packet as the original 598.55
keyframe, normalized to zero. Corrected MP4 comparisons copy directly from the
full saved baseline picture, preserve edit-list preroll, and check the first
displayed frame against the intended original frame after mux. Existing fixture
sources/exports remain preserved and are not presented as absolute alignment
proof. Future fixture preparation aligns all tracks to a verified keyframe first.
Short absolute-timestamp comparison rendering and cumulative raw-cache accounting
are now available in the evaluation tool.

Changed files: second-pass interpretation/version, evaluation tool, two test
files and docs. Verification: 135 tests, 134 passed, one existing fixture skipped
(`stage10-tests.log`). The picture test demonstrates the old drift and checks the
corrected displayed frame. The full cached controls have been refreshed into
`cached-minute-final` and `cached-long-600-790-final`: 7/7 and 25/25 placements,
zero translation, ASR or TTS calls, exact continuous game-plus-voice PCM.

Exact next step: let `queue-final.log` finish; it began before interpretation 4,
so run the saved queue once more with current code to settle all fingerprints.
Matching providers/raw takes must be reused; inspect the returned `Intentar`
confirmation and the uncertain `Gracias` result explicitly. Rerender all
comparisons with the corrected picture tool, create timestamped excerpts, run
the unchanged-resume check and write final counts/limitations. The refreshed
minute renderer is in `minute-render-final.log`.

## Stage 11 — bilingual verdicts for the actual compact repair

Completed: the longer passage trace showed a fit repair changing `I hope it
hasn't seen me` through two rewrites to `hope I'm not seen`, while retaining the
initial wording's bilingual review status. Such a stale verdict can no longer
authorize a repaired line. Performance scheduling withholds the current rewrite;
the configured unattended coordinator requests bounded bilingual review using
the existing configured roles, stores text-bound requests/responses/audits under
`handoff/repair_reviews/`, and resumes with its owned job lock. Review may restore
meaning even if that makes fit harder. A disputed or unconfirmed result remains
partial/unvoiced. Already reviewed identical text needs no new provider call.

Changed files: fidelity, pipeline metadata/gate, quality flow, review context,
unattended coordinator, regression tests and docs. Verification: 136 tests,
135 passed, one existing fixture skip (`stage11-tests.log`). The focused test
restores observer/completed-action wording, keeps neighboring text, refuses a
stale verdict after another edit and checks unchanged resume needs no review.

Independent verification now saved: `resume-proof.json` compares 420 minute
synthesis/provider/output/schedule files across resume: zero additions/removals/
changes, all stages unchanged, honest partial exit 3. `candado-replay/evidence.json`
replays just duplicate filtering on the exact original saved hearing and source
spans, with no new ASR/provider/TTS: `A ver este candado` survives intact.

Exact next step: finish the current serial queue (it is past the long passage).
Then repeat `run-set` with current code to apply interpretation 4 and repair-review
binding to all experimental jobs. This should recover the corroborated `Intentar`
reading using both existing hearings. Inspect any compact repairs and reviewer
changes; reuse matching saved responses/takes. The minute excerpts are being
rendered in the background. Finish corrected comparisons, remaining excerpts,
final counts/preservation/resume evidence, results docs and commit.

## Stage 12 — reaction timing in both collection paths

Completed: the final constraint review found that performance reactions could
still use the older early-start fallback, and the legacy collector lacked the
vocal-event protection already present in best-of-N. Both collectors now refuse
to advance a timed reaction into earlier gameplay. Fixed vocal realizations also
cannot request a meaningless compact rewrite in the legacy path. Ordinary source
anchors and later cues remain fixed; protected preroll and bounded local lead
budget are unchanged.

Changed files: line collection, performance schedule identity, regression tests
and this note. Verification: 137 tests, 136 passed, one existing recorded fixture
skip (`stage12-tests.log`). The test checks both collectors with a valid take
that would otherwise fit only by starting 300 ms early. Schedule version 5 affects
selection/presentation only, preserving raw ASR, source analysis, provider requests
and generation identities.

The settled passage set before this final safeguard is 44 retained/translated,
35 placed, nine explicitly withheld; minute 7/7 and long 21/24. All nine current
comparison MP4s check their displayed source origin. Final unchanged-resume proofs
cover 649 minute and 1,139 long-passage cache/provider/transcription/schedule/output
files with no additions/removals/changes (`resume-proofs-final.json`).

Exact next step: checkpoint current voice hashes and protected raw/provider/ASR
files, then repeat the serial queue under schedule version 5. Confirm this safeguard
changes no selected audio in the demonstrated set (all selected takes had zero
early shift). Refresh final accounting and unchanged-resume proofs. Finish and
commit measured results documentation and preview-tool labels; do not run fresh
translation or TTS unless an actual changed request/take requires it.
