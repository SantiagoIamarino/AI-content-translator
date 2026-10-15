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

Exact next step: create isolated evaluation jobs and a microphone-bound 00:10
annotation (user-confirmed event, approximate end from saved lexical onset).
First compare identical cached takes under old/new processing and selection.
Then run this checkout's configured providers/synthesis on the first minute and
representative long passages. Preserve original jobs and paid response identities;
record separate fresh-generation counts, omissions/uncertainty and media checks.
Render timestamped Spanish/prior/new comparisons, verify repeat resume, and commit
the evaluation tooling, final evidence documentation and updated progress note.
