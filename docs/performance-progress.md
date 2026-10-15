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

Exact next step: implement an opt-in timed source-event ledger bound to microphone
hash and timestamped evidence. Represent confirmed hesitation and uncertainty
inside cues, propagate it through translation/synthesis/placement, and test that
noise/unknown events cannot become English words. Preserve the approved reference
pair, fixed Qwen generation, trim settings, and tempo ceiling.
