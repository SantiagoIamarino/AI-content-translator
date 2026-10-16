# Dubbing optimization implementation plan

Status: batch 1 accepted for continued development; batch 2 implemented and
verified with focused fake-provider/media tests in the same isolated worktree on
2026-10-16. Neither batch is integrated into the operational checkout. Batches
3–6 remain proposed and unimplemented. The original observations were inspected at approximately
20:15 UTC. The user subsequently authorized batch 1, focused tests, and a check
of at most eight existing WAVs, with no providers, Qwen synthesis, full-video export,
or mutation of existing jobs. Completion evidence is recorded below.

## Outcome and constraints

Deliver faithful, natural, calm English commentary from Spanish gameplay through
one configured unattended command, with bounded recovery and no follow-up prompts
on the normal path. GPT-6 Luna becomes the explicit primary provider through
ChatGPT authentication. Minor uncertainty must not silence supported meaning;
material ambiguity must remain visible and receive bounded evidence-based review.
Spanish comparison export becomes optional and defaults to off for new jobs.

Preserve these comparison conditions throughout batches 1–6:

- Approved tranquil reference B and its approved transcript, Qwen English ICL,
  model revision, generation settings, and seeds for matched comparisons.
- Trim RMS 0.005, window 10 ms, pad 0, and cumulative tempo at most 1.10.
- Source-supported hesitations, connectors, repetitions, pauses, soft endings,
  protected generated signal, and fixed gameplay reaction anchors.
- Continuous unscaled game samples and copied picture. Insufficient game
  headroom and unavailable/approximate checks remain explicit limitations.
- Transcript text is data. Provider configuration and executable instructions
  cannot come from transcript text, quoted diagnostics, or model responses.
- Existing job snapshots remain authoritative. Retain recordings, caches,
  attempt identities, responses, and historical reports; do not delete them to
  recover or migrate.
- Hold one owned job lock through provider handoffs and acceptance; pass it into
  `run_job`. Never reacquire that lock or delete `LOCK` to bypass another runner.
- Technical complete requires all kept content placed, no open repairs or missing
  required verification, and all required gates passed. Listening approval is
  recorded separately.

Adaptive candidate reduction is deferred until batches 1–6 have been evaluated.
Keep the current four-valid-candidate policy and bounded extra attempts initially.
Do not introduce several independent Qwen processes on the GPU.

## Implementation isolation and existing work

The inspected branch is `fix/conversational-continuity-20261015`, at
`8926c7f1d9e56d2fd544fc4bed92c0d3832bff3e`. The working tree already contains
recovery changes; HEAD alone is not the running implementation baseline.

| Existing state | Files |
| --- | --- |
| Modified tracked files | `README.md`, `aidub/cli.py`, `aidub/pipeline.py`, `aidub/schedule.py`, `bin/aidub`, `tests/test_core.py`, `tests/test_performance.py` |
| Untracked source, tests, and documentation | `aidub/targeted_review.py`, `scripts/provider_codex.py`, `scripts/test_provider_codex.py`, `scripts/overnight.py`, `scripts/test_overnight.py`, `docs/overnight.md` |
| Untracked operational evidence | `runs/overnight/` |
| Ignored job/config evidence | Job snapshots, model/media caches, and workstation-local provider/reference configuration |

The tracked diff currently reports 162 insertions and six deletions across seven
files. It includes corrective tempo and verification-timeout fingerprint changes.
The targeted acceptance command depends on an untracked module. Codex and overnight
support are also untracked. Preserve these dependencies when preparing a baseline.

When implementation is separately authorized:

1. Reinspect HEAD, status, diff, and active work before preparing an isolated
   checkout. Do not edit Python modules imported by a live runner in this checkout.
2. Create a separate worktree and implementation branch from the recorded commit
   using the approved repository. Running this checkout's `bin/aidub` with its
   configured shared virtualenv interpreter is permitted. Do not modify the
   historical project/environments or import its `aidub` implementation; do not
   migrate or reinstall environments unnecessarily. Do not reuse another worktree
   by assumption or prune old worktrees.
3. Transfer the reviewed tracked diff and only the named untracked source/tests/docs
   into that worktree. Record their hashes and provenance as the recovery baseline;
   verify the baseline is complete before adding optimization changes. Do not
   blanket-copy untracked files, job trees, operational logs, credentials, or media.
4. Preserve the original checkout and its local changes. No stash, reset, branch
   switch, commit, or movement of those changes is part of document preparation.
   Future commits/review must distinguish the recovery baseline from each batch.
5. Use isolated temporary jobs and the isolated checkout's own `bin/aidub` for
   authorized execution. Keep executable paths, credentials, models, reference
   assets, and evaluation job roots in ignored local configuration. Do not install
   packages/models or start unrelated services as part of this plan.
6. Integrate approved changes into the operational checkout only when its runner
   is inactive and the integration is separately authorized. Job migration requires
   an owned job lock, a retained previous snapshot, and an explicit migration record.

The preparation instructions above describe the original plan. Batch 1's isolated
baseline and implementation commits are now recorded in the completion section;
no existing job was migrated and nothing was merged or pushed.

## Observed baseline and measurement limits

These are observations of one recovery history, not a clean throughput benchmark.
Evidence is under `jobs/gameplay_oct15_performance/` and
`runs/overnight/gameplay_oct15_performance/`.

| Observation | Evidence and limitation |
| --- | --- |
| Source length: 5,275.783333 s, about 87m56s | Saved inspect/report metadata; media was not processed for this plan. |
| Latest validation: partial, 746/790 placed, 44 omitted | `report/validation.json`, written at 20:06:14 UTC; matches schedule/mix summaries. Manifest says partial with stages complete. Supervisor's saved status is `partial_terminal`, finished at 20:06:56 UTC. These are dated saved states, not permission to resume. |
| Current omission reasons | 28 source/review uncertainty, six material ASR conflicts, three protected-edge failures, three tempo-limit failures, two unsettled endings, one abnormal-rate rejection, one explicit unresolved repair. |
| Earlier baseline: 678 placed, 112 omitted; 544 placed lacked primary ASR evidence | Retained `report/targeted-recovery-before.json`. All 746 currently selected takes have primary ASR evidence. This does not prove that every requested second hearing completed. |
| Targeted recovery enabled 70/104, retained 34 disputes, revised ten English lines | `report/targeted_review_acceptance.json`. Net placed gain is 68; two enabled cues still fail protected-edge fit. This was per-job recovery, not normal automatic behavior. |
| Remaining uncertainty exceeds omitted-cue counts | Latest uncertainty report contains 110 unintelligible source spans, 34 disputed translations, and six material conflict entries; event report has 38 unresolved entries among 42 events. Scopes overlap; do not sum them as unique omissions. |
| Provider history: 82 attempt records; stored intervals total 27,415.8 s, about 7h37m | Recursive census of provider-state records. Recovered responses can acquire later end times; this is not pure provider latency. The saved report's narrower counter says 65 attempts and omits other scopes. |
| Luna targeted-review samples: six successful batches around 6.4–14.7 s; two earlier invalid attempts | Saved attempts. Smaller/different payloads than earlier provider work; insufficient for a full-job speed claim. |
| Source transcription: first recorded stage 283.5 s | Stage includes the work inside that stage, not an isolated Whisper inference benchmark. |
| 4,058 unique synthesis metadata records; recorded inference total 8,603.0 s | Includes recovery generations. Does not include all initialization, verification, or presentation. |
| Scheduling: first recorded pass 8,251.8 s; all recorded passes 11,012.0 s | Includes synthesis/verification/presentation. Do not add these totals to synthesis inference. |
| Six full mix/export passes; recorded mix total 9,262.3 s | Full passes take about 19–29 minutes; additional cache-hit invocations are included in the total. One Spanish comparison is approximately 53.3 GB. |
| Seven successful full validations plus one short failed pass; total 8,295.6 s | Successful passes take about 19.5–20.1 minutes. This supersedes the earlier six-pass count. Components are not timed separately. |
| Warm inspection often takes 64–70 s | `stage_inspect` hashes the source before checking stage reuse. Strong source-integrity checks must survive any later optimization. |
| Two reboot-recovery records | Account for known host downtime separately. Sampling gaps remain unknown. NVIDIA/DisplayPort freezes are not established pipeline bugs. |

The job-specific candidate deadline is now 600 seconds on CUDA. This is not a
validated new global default. The five-second subprocess exception corresponds
to a cleanup/reap wait in `AsrClient.close`; retained evidence does not establish
the original CUDA failure.

Whole-video 4–7-hour and 2–4-hour targets remain unproven hypotheses. Do not add
overlapping savings from Luna, concurrency, scheduling, and fewer finalizations.
Measure the changed stages before forecasting an integrated duration.

## Evaluation rules shared by all batches

Use `test-media/gameplay_oct15_first150s.mp4` for short comparisons. Its existing
preparation record reports 150.016667 s video, 150.016 s for each of three AAC
streams in original order, and H.264 2560×1440 at 60 fps. Its inspected file size
is 387,243,138 bytes. Use the original mic/game/mixed roles recorded for this
recording; generic stream titles do not establish roles for other recordings.
Do not substitute a Spanish comparison export as a multi-track test input.

- First use focused fake-worker/provider and metadata fixtures. Run only tests
  relevant to the changed behavior; do not rerun the pipeline after every edit.
- Reuse identical requests only under their matching provider/contract identity.
  Saved responses test deterministic acceptance/recovery, not live provider speed.
- Reuse identical text/seed/reference/generation WAVs for verification and
  presentation comparisons. Existing audio need not be synthesized again.
- Distinguish fresh provider execution, fresh synthesis, application-cache hits,
  cold model initialization, warm inference, hashing, and finalization. Never
  compare a warm replay total against a cold baseline as a speed improvement.
- Select short reactions, supported fillers, soft endings, actual ambiguity, and
  apparent discourse false positives from existing evidence as needed. The first
  150 seconds alone does not represent all these cases.
- Use separate evaluation job roots. Existing long-job artifacts are evidence,
  not mutable test fixtures; existing evaluation helpers may acquire baseline
  locks, so inspect their behavior before using them.
- Keep a small evaluation receipt: implementation/recovery-baseline identities,
  config and input hashes, reference/generation identity, cache disposition,
  stage boundaries, actual provider attempts, cue/span counts, and gate results.
  Avoid a new general tracing framework in batch 1.

Before claiming integrated improvement, audition the full short clip and 12
source/baseline/candidate excerpt sets, about 10–20 seconds each: three random,
three disputed/recovered, two reactions, two soft endings, and two quiet-game
passages. Randomize baseline/candidate order. Record meaning errors, unsupported
additions, omissions, filler function, timing, calmness, identity, endings, and
game audibility with timestamps. Require zero material meaning errors or audible
truncated endings and no systematic calmness/identity regression. Ratings such
as median at least 4/5 help compare versions but are not identity proof or a
substitute for defect notes. Technical gates are not human listening approval.

## Batch 1 — ASR correctness and reusable evidence

**Problem and intended behavior.** Existing persistent workers are sufficient;
the defects concern lifecycle, evidence completeness, and cache identities.
Cleanup can mask the initiating error and drop the process handle before reaping.
An unrecovered first-hearing error disables verification for the scheduling pass.
A failed second hearing can remain `ok`, be cached, and satisfy a primary-ASR-only
gate. Fallback rebuilds the identity without glossary names. Assessment uses pacing
settings absent from the quality identity; hashing all of `selection.py` also
couples ranking implementation to ASR reuse.

Implement these bounded changes:

1. Preserve the initiating error, diagnostic tail, and separate cleanup/reap
   outcome. Retain ownership of an unreaped process; do not launch its replacement.
2. Distinguish complete evidence, incomplete evidence, and actual audio/check
   failure. A triggered second hearing is part of evidence completeness. Its
   infrastructure failure must not become a pass, an audio rejection, or an
   invitation to regenerate otherwise usable speech.
3. Bound recovery to at most one same-device restart and one configured CPU
   fallback per failed hearing/recovery episode. Persist the episode's attempts
   so resume cannot loop indefinitely. Preserve existing deadlines initially.
   Exhaustion stops resumably with the affected WAV/evidence identified. No new
   public job state is required merely to represent pending verification.
4. Construct effective identity through one path, retaining sorted glossary names,
   model/weights, language, decode settings, environment/worker provenance, and
   actual device. Keep provenance for each hearing if devices differ.
5. Separate reusable hearing/waveform evidence from assessment decisions using a
   small versioned record/key change in the existing cache machinery. Include all
   decision-affecting settings, including pacing rejection thresholds, in the
   assessment key. Ranking weights and candidate counts must not invalidate raw
   hearing/waveform evidence. A checker change may recompute decisions from that
   evidence without another hearing when the stored fields suffice.

**Likely modules.** `aidub/asr_client.py`, `_LineAssessor` and scheduling/final
verification gates in `aidub/pipeline.py`, `aidub/verification.py`; narrowly scoped
changes in `aidub/quality.py` or `aidub/selection.py` only where needed to separate
assessment inputs from ranking. Use existing checkpoint/atomic-write helpers.

**Dependencies.** Complete isolated recovery baseline. No dependency on Luna,
provider concurrency, new source segmentation, or a supervisor rewrite. Keep the
synchronous one-request protocol and fresh queue per worker; no request IDs,
worker-generation protocol, or ASR request pool in this batch.

**Minimal meaningful tests.** Extend the existing hardening/performance fixtures:
original error survives failed shutdown/reap; no replacement while unreaped;
bounded recovery remains exhausted after resume; CUDA fallback retains names and
device identity; failed second hearing remains incomplete and retries only missing
evidence; final gates reject incomplete required verification; cached real audio
failures stay failures; changed pacing thresholds recompute decisions; changed
ranking weights/counts reuse evidence with zero ASR calls. Include processed-take
and focused-prefix evidence so neither bypasses completeness accidentally.

**Calls and synthesis.** Unit checks need fake workers only. After they pass, use
at most eight existing representative WAVs for one small local-ASR check: one cold
worker startup followed by warm requests, with controlled fake failures covering
recovery. No provider calls or fresh Qwen synthesis. Do not induce host/GPU faults.

**Cache/migration and rollback.** Keep raw WAV keys and bytes unchanged. Version
new evidence/assessment records; preserve legacy records. Trust legacy summaries
only when their complete successful evidence and required inputs can be established;
otherwise re-hear existing WAVs. Never fabricate unavailable word-level evidence
from summary text. Invalidate affected quality/schedule decisions and downstream
outputs when necessary, not source ASR or translation. Retain prior cache namespaces
and config for code rollback; old code must not read incompatible new records.

**Acceptance and next-batch evidence.** All focused checks pass; no masked initiating
error, unbounded retries, unreaped replacement, incomplete-verification pass, or
fallback identity loss. The existing-WAV receipt separates cold/warm time, shows
zero provider/synthesis calls, and demonstrates evidence reuse after ranking-only
changes. Batch 2 can then proceed without a new full export.

## Batch 2 — Two small orchestration fixes

**Problem and intended behavior (pre-batch-2 baseline).** `run_unattended` calls `review_pending_repairs`
only after `run_job` has returned partial, following mix, export, validation, and
risk reporting. `run_review` requests back-translation even after its last round,
although no following decision consumes it. Move compact-repair review ahead of
expensive finalization, and request back-translation only for an identified next
consumer. Preserve confirmation of the actual repaired English and bounded rounds.

**Likely modules.** `aidub/unattended.py`, `aidub/quality_flow.py`, `aidub/review.py`,
and the smallest pre-finalization hook/control change in `aidub/pipeline.py`.

**Dependencies.** Batch 1 accepted; unchanged owned-lock semantics. The hook must
also support the later source-resolution coordinator. Manual operation must stop
with a clear handoff when confirmation is required rather than silently calling an
unconfigured provider or weakening fidelity gates.

**Minimal meaningful tests.** With fake providers/media stages, prove review occurs
before any expensive finalization; an unresolved or revised-unconfirmed repair is
still blocked; accepted text is the exact scheduled text; repeated resume reuses
matching responses; lock ownership survives the hook; review/revision budgets are
not reset by the new loop. A one-round review makes no unused back-translation;
earlier rounds still receive it when needed. Confirm unchanged output decisions on
cached review fixtures.

**Calls and synthesis.** No model calls or fresh synthesis are necessary to prove
ordering and unused-call removal. Use cached text/responses for behavior comparison.
Do not run the 150-second pipeline solely for this batch.

**Cache/migration and rollback.** Preserve accepted responses and raw takes. Record
an orchestration/review-policy version without changing unrelated request identities.
Do not present an old audit's missing final back-translation as corruption. Changed
repair text invalidates its own assessment/schedule/downstream results. Rollback
restores prior control flow and retained snapshots, without deleting newer history.

**Acceptance and next-batch evidence.** Call-order/count fixtures show no full
finalization before pending repair review and no unconsumed final back-translation.
Required fidelity decisions and lock behavior remain intact. Try this narrow change
before introducing separate checkpoints for every finalization component.

**Implementation status.** Completed in the isolated worktree only; see batch-2
completion evidence below. The small control change is an explicit
`awaiting_repair_review` handoff before scheduling, handled by auto under its
existing lock. No finalization-checkpoint framework was added.

## Batch 3 — Harden and configure Luna as primary

**Problem and intended behavior.** The existing adapter explicitly invokes Luna
with medium reasoning but hardcodes both, overwrites reported model metadata, and
does not enforce subscription authentication. Provider identity does not bind the
adapter's implementation. Review combinations can be schema-valid yet disagree
about downstream eligibility. Make Luna the normal configured primary for context,
translation, review, back-translation, and repair; do not depend on Cursor selection
or silently fall through to API billing or another provider.

**Likely modules.** `scripts/provider_codex.py`, `aidub/providers.py`,
`aidub/config.py`, `aidub/review.py`, `aidub/quality_flow.py`, local/example config,
and provider documentation. Inspect supervisor transition code before migration.

**Dependencies.** Batches 1–2. Validate the installed CLI's supported authentication
and confinement controls before implementing command flags. Start with explicit
`gpt-6-luna`, reasoning `medium`, for every role; role-specific alternatives require
later evidence. ChatGPT login is an initial setup prerequisite, not an overnight
interactive prompt. Official background:
[authentication](https://learn.chatgpt.com/docs/auth) and
[structured noninteractive output](https://learn.chatgpt.com/docs/non-interactive-mode).

Use a shared, versioned contract validator and decision reducer for normal and
targeted review. Validate source uncertainty independently from translation fidelity;
reject contradictory or underspecified combinations rather than treating valid JSON
as sufficient. Keep exact IDs/text binding, changed-text requirements, confirmation
status, and transcript-as-data handling. Implement only the contract foundation
here; acoustic adjudication belongs to batch 5.

Require ChatGPT authentication in the effective CLI configuration/environment and
fail before model invocation on a known mismatch. Keep credentials in the existing
local credential store; do not log or copy them. Bind effective model/reasoning,
adapter/prompt/schema versions, auth mode, and relevant confinement settings into
provider provenance/identity. Prompts alone are not tool-execution confinement.

Retain outer timeouts, response size limits, persisted retry budgets, validation
feedback, and process-group cleanup. Atomically persist a valid final response
before optional diagnostics. Preserve uncertain external outcomes when no response
is durable. Reuse validated saved responses before attempting new calls. Explicit
authentication/quota/configuration failures stop actionably; never retry forever.

**Minimal meaningful tests.** Fake CLI checks for all five role schemas, effective
model/reasoning/auth selection, prohibited auth/provider fallback, exact IDs, null
normalization, unchanged `revise`, and uncertainty/fidelity consistency. Recovery
fixtures cover response-before-state interruption, corrupt canonical response with
valid saved attempt, expired attempts, uncertain completion, and semantic validation
feedback. Changed model/reasoning/adapter contract must not reuse another identity.

**Calls and synthesis.** No calls for contract/auth-configuration fixtures. After
those pass and account readiness is confirmed, make at most one representative live
call per role whose final contract lacks matching evidence: at most five calls.
Saved responses then support acceptance/recovery tests. No fresh synthesis.
Quota, account concurrency, and long-context latency remain measured unknowns.

**Cache/migration and rollback.** New jobs use the explicit primary mapping; portable
config remains unconfigured until local prerequisites are supplied. Existing jobs
retain snapshots, accepted responses, original provider provenance, and budgets.
Changing provider configuration alone must not relabel cached context/translation
as Luna output. Migrate a stopped job explicitly under its lock, recording which
accepted historical results are retained and which pending calls use new identities.
Retain the old snapshot for rollback; do not silently switch providers on rollback.

**Acceptance and next-batch evidence.** Every role produces a meaningful validated
decision; no API-billing fallback or hidden inherited model choice. Saved-response
recovery passes without duplicate calls, uncertainty is retained, and each live call
has explicit model/auth provenance. Configuration supports one normal unattended
invocation after initial setup, with clear bounded failure when prerequisites fail.

## Batch 4 — Optional Spanish comparison, off for new jobs

**Problem and intended behavior.** `stage_mix` always generates the full comparison;
mix cache requirements and `stage_validate` require it. Risk previews, storage
estimation, reporting, and evaluation helpers assume it exists. Introduce an explicit
comparison-export setting: false for new jobs, optional full export on request,
and short comparison excerpts for experiments. A leftover old file does not mean
the current configuration requested or validated a comparison.

**Likely modules.** `aidub/pipeline.py`, `aidub/export.py`, `aidub/storage.py`,
`aidub/risk.py`, `aidub/report.py`, `aidub/config.py`,
`scripts/performance-evaluate.py`, `scripts/continuity-evidence.py`, config/docs.

**Dependencies.** Batch 2's ordering fix. Inventory required files, fingerprints,
check lists, report fields, preview audio mapping, and evaluation fallbacks before
removing any dependency. Source previews must select the configured mixed audio
ordinal, not assume `0:a:0`; retain established picture/time origins.

Keep English source integrity, source-to-English bitstream identity, decode,
duration/geometry, one English default audio track, encoded audio, PCM lengths,
clipping/headroom, game-bed reconstruction, subtitles, placement, verification,
protected endings/events, coverage, and source-resolution gates. Comparison-only
checks are conditional or reported not requested, never converted to fake passes.
Use the source directly for required English checks and bounded Spanish previews.

**Minimal meaningful tests.** Default off and explicit on for new jobs; legacy
snapshot behavior; conditional required files/fingerprints; stale comparison ignored;
correct mixed ordinal; storage estimate with one/two full video exports; source
preview timing; reports for absent optional output. Use one tiny generated media
fixture to exercise both modes and prove English gate equivalence, including an
English failure that remains a failure when comparison is off.

**Calls and synthesis.** No model calls or fresh synthesis. After fixture checks,
use matched cached English text/takes on the prepared clip to compare finalization
with comparison off/on, recording mux/hash/decode costs separately. These media
checks require later execution authorization and do not validate cold synthesis.

**Cache/migration and rollback.** Resolve missing comparison settings as legacy-on
for existing snapshots; write explicit false into new snapshots. Explicit migration
changes only optional export/validation/preview dependencies, preserving source ASR,
translation, and raw synthesis. Avoid unnecessary English remuxing; introduce a
small optional-output checkpoint if needed, not a broad stage rewrite. Preserve old
comparisons. Restore prior explicit setting and retained fingerprints for rollback.

**Acceptance and next-batch evidence.** A new comparison-off job validates directly
against its source with all English protections intact, correct previews, and no
full Spanish output. Explicit-on works. Record actual avoided bytes and measured
short-clip finalization differences; do not extrapolate a fixed long-job time saving.

## Batch 5 — Automatic bounded uncertainty resolution

**Problem and intended behavior.** Minor wording doubt can withhold entire cues;
token-presence polarity checks conflate discourse `Nada...` or trailing `¿no?` with
material negation. Targeted acceptance cannot override an existing material conflict;
scheduling and validation block on that flag independently. Targeted revisions also
lack the normal path's final-text confirmation rule. Integrate useful recovery into
`auto` before finalization without approving every dispute or lowering thresholds.

**Likely modules.** `aidub/fidelity.py`, `aidub/review.py`,
`aidub/targeted_review.py`, `aidub/quality_flow.py`, `aidub/unattended.py`,
source uncertainty/event reporting in `aidub/pipeline.py`, and focused helpers in
`aidub/second_pass.py`/`aidub/events.py`. Boundary diagnostics may touch segmentation
or grouping modules; broad resegmentation is outside this batch.

**Dependencies.** Batches 1–3 and the pre-finalization hook. Use three independent
decisions: source evidence (supported/minor/material ambiguity), translation fidelity
(accepted/revision pending/material error), and synthesis eligibility (full/supported
spans/withheld). One reducer must drive acceptance, scheduling, and validation.

Resolve only supported meaning. Minor grammar, fillers, or equivalent readings are
normally non-blocking. Material ambiguity about polarity, actor, action, number, or
referent receives one bounded contextual acoustic review and at most two semantic
rounds, with persisted per-evidence budgets and no repeated identical hearing.
Use only already provisioned local ASR models. Back-translation informs English
fidelity; it is not new acoustic evidence or proof of the Spanish reading.

Bind resolutions to microphone identity, source span, alternatives, acoustic
model/options, and exact reviewed text/evidence. Keep original conflicts in history
and attach explicit resolutions rather than deleting flags. Normal and targeted
paths must require confirmation of revised final English; a last-round revision
remains pending unless the remaining configured budget confirms it. Do not add
unbounded confirmation rounds.

Recover independently supported clauses where boundaries/evidence allow, using
stable parent/child span lineage and visible unresolved remainders. Include uncertain
gaps and vocal events, not only translated cue disputes. Do not automatically speak
short ASR hallucinations from noise. Retained material unknowns keep technical partial
status. Detect implausible/overlapping boundaries before spending fit/repair budgets;
the cue 376/377 overlap demonstrates that shortening text cannot fix every window.
Stop for a scoped boundary correction when needed; preserve reaction anchors and
protected endings rather than forcing content into an impossible window.

**Minimal meaningful tests.** Discourse markers versus true negation; grammar-only
uncertainty; context agreement without acoustic support; supported clause plus unknown
remainder; stale microphone/span/text binding; all three consumers recognizing the
same resolution; revised text requiring confirmation; bounded resume; noise versus
hesitation; overlapping duplicate spans versus genuinely separate reactions.

**Calls and synthesis.** Start with cached evidence/provider decisions. Then use at
most 12 focused source cases selected before execution, containing both recoverable
minor doubts and genuine material-ambiguity controls. Fresh local hearings only where
matching evidence is absent; at most two batched semantic rounds within the chosen
subset. Reuse existing takes when English is unchanged. Fresh synthesis is necessary
only for changed/recovered English without matching takes; retain the fixed candidate
policy. This is the first coverage-changing batch requiring listening comparisons.

**Cache/migration and rollback.** Version resolution policy and evidence separately
from the transcript. Invalidate affected eligibility/assessment/schedule/downstream
results, not all translations or raw WAVs. Splits need explicit lineage/new IDs and
new requests for affected spans; do not silently resegment an existing long job.
Retain old decisions, text, and artifacts. Rollback restores prior policy/snapshot
without treating newer decisions as compatible or deleting recovery evidence.

**Acceptance and next-batch evidence.** All sampled exclusions are explained; supported
portions are recovered without material additions, polarity flips, filler loss, or
new timing/voice/ending defects. Genuine ambiguity controls remain unresolved when
evidence cannot decide. Acceptance, scheduling, and validation agree. Record recovered
source spans and residual unknowns separately from cue counts. Required gates and the
short listening protocol pass before batch 6's integrated performance comparison.

## Batch 6 — Limited provider concurrency

**Problem and intended behavior.** `invoke_batches` runs independent calls serially.
Begin with a bounded pool of two provider calls, deterministic aggregation, shared
frozen context/glossary, and unchanged request identities. Context parts currently
depend on prior context; keep them sequential. First parallelize within translation
and within review. Defer cross-stage overlap until evidence shows another bottleneck;
any later review overlap requires translated neighbors and stable source decisions.
Keep placement and running voice-consistency selection ordered.

**Likely modules.** `aidub/batches.py`, `aidub/quality_flow.py`, `aidub/providers.py`
only as necessary for bounded cancellation/recovery, configuration, and focused
provider-attempt measurements. No parallel Qwen pool or general workflow engine.

**Dependencies.** Accepted durable provider identities/recovery from batch 3 and
stable coverage behavior from batch 5. Limit two must cover all in-flight provider
work in the job, not two calls independently for every role/stage. Respect observed
account limits; do not assume subscription capacity. Keep the outer job lock owned
until aggregation and acceptance, with per-batch locks for attempt records.

**Minimal meaningful tests.** At least four fake batches to exercise queueing and
out-of-order completion; one invalid response, one timeout, interruption while another
response is saved, duplicate runner rejection, aggregate ordering/IDs, identical
context, limit two, persisted budgets, and response reuse on resume. A failed call
must not discard completed siblings or launch duplicates during cancellation.

**Calls and synthesis.** Start with one paired serial/concurrent experiment using
two realistic translation payloads and two review payloads with frozen neighbor
context from saved records. Execute the two translation batches then the two review
batches under each condition: eight fresh calls total. These are independent replay
inputs for executor measurement, not a claim that frozen reviews evaluate newly
generated translations. Use separate evaluation execution namespaces with the same
semantic request/provider inputs; do not alter request text to defeat cache reuse.
Record cache misses, actual invocation intervals, account throttling, and ordering.
Keep all returned outputs for fidelity review.

A single normal provider batch from the 150-second clip cannot test concurrency.
Use the multi-batch payload set above; fake tests cover longer queues. No synthesis
is needed for this experiment. If latency variation, throttling, or invalid outputs
make the decision unclear, run at most two additional paired trials, alternating
order: at most 24 fresh calls total. Report individual pairs and median/range;
do not infer a reliable p95 from three trials or use 1.3× as a correctness gate.

**Cache/migration and rollback.** Concurrency must not change semantic request,
provider, response, synthesis, or assessment identity. Evaluation namespaces keep
fresh execution separate from cache-reuse trials. Persist explicit concurrency in
new config; existing snapshots remain serial unless migrated while stopped. Roll
back by setting concurrency one, retaining all sibling responses and attempt budgets.

**Acceptance and next-batch evidence.** Maximum two in-flight calls, no duplicates
or discarded valid responses, coherent aggregation and cross-batch terminology,
and no coverage/fidelity regression. Adopt two only when measured elapsed work
improves without unacceptable failure/throttling; otherwise keep serial. Report
uncertain outcomes and retry cost alongside speed. Do not claim provider speed
from a cached response or whole-video speed from this executor experiment.

## Integrated checkpoint and deferred work

After the six batches pass their focused gates, run one fixed-generation short
comparison with comparable cache/model conditions. Reuse matching accepted text
and takes; synthesize only missing changed text, and report those costs separately.
Use source/English excerpts instead of requiring a full Spanish comparison.

A single 15–30-minute integrated run becomes justified after short listening,
provider multi-batch behavior, source resolution, and recovery fixtures pass. Use
multiple real batches, sparse reactions, quiet gameplay, and soft endings. Follow
with one controlled interruption/resume outside a provider call. An unchanged warm
resume should invoke zero providers and generate zero takes; repeat media work only
when input identities or required evidence changed. A representative 1–2-hour run
is justified after that checkpoint, not after every edit.

Retain a minimal trustworthy history throughout: processed, placed, exported,
partial, and validated are distinct facts; record current output/validation identity
and archive resolved errors. Provider counts must cover context, main batches,
targeted recovery, and repair review without counting reused evidence as new calls.
Local supervision remains independent of the AI session, never kills a healthy
worker merely for quiet logs, and cannot reset retry budgets or start duplicate
runners. Wider metrics/supervisor cleanup can be a separate small batch when the
evaluation receipts demonstrate a concrete need; do not bury it in batch 1.

Only then consider adaptive candidate reduction, broader gate caching, or more
cross-stage overlap. Replay fixed candidate sets first and preserve high-risk full
budgets. Changes to candidate selection require fresh listening evidence; faster
processing cannot be bought through stripped vocal events, universal shortening,
chopped endings, unverified audio, or voice drift.

## Batch 1 completion evidence — 2026-10-16

### Isolation and identifiers

Implementation is in the separate worktree `ai-dubbing-e2e-asr-batch1`, branch
`fix/asr-correctness-20261016`:

- Operational source HEAD: `8926c7f1d9e56d2fd544fc4bed92c0d3832bff3e`.
- Reviewed recovery baseline: `418f205b968e66bd1511a9a1cdfd321263328be6`.
- Batch-1 implementation: `17d23353372cf19ab02def3555bc6e37e40706f1`.

The baseline carries only the seven modified tracked files and seven named
source/test/documentation files, including this plan. Operational logs, jobs,
credentials, media, and local configuration were excluded. A local baseline
receipt records transferred-file hashes. The operational recovery files still
match those baseline hashes; its plan received only the requested clarification
that the configured shared interpreter is permitted. No historical implementation
was imported and no environment was migrated, installed into, or edited.

No active dubbing/ASR worker was found at preparation. This was rechecked after
the user interruption. Existing jobs were not resumed, locked, or modified. All
evaluation jobs/locks/writes belong to the isolated worktree.

### Changed behavior and files

- `aidub/asr_client.py`: initiating exceptions survive failed cleanup; process,
  pipes, and diagnostics remain owned until reap succeeds; no replacement while
  cleanup is incomplete. The synchronous JSON-lines protocol remains unchanged.
- `aidub/pipeline.py`: each actual hearing has an atomic recovery record and a
  bounded persisted budget. Default CUDA episodes allow initial request, one CUDA
  restart, then one CPU fallback; CPU episodes allow initial request plus one
  restart. An unreaped worker also blocks other WAVs through a job-wide ownership
  record. A successful reap releases that block. Fallback retains glossary names
  and cannot be undone by a cached GPU hearing during the CPU pass.
- `aidub/pipeline.py` and `aidub/verification.py`: an infrastructure failure in a
  triggered second hearing is explicitly incomplete. It stops resumably instead
  of generating replacement candidates. Resume retains completed first-hearing
  evidence. Focused-prefix and processed-take checks use the same recovery and
  completeness rules. Mix/final gates reject known incomplete verification.
- `aidub/quality.py` and `aidub/verification.py`: raw hearing and waveform facts
  are reusable separately from assessment. Assessment identity includes effective
  rejection thresholds, names, reference/checker provenance, and coordinator
  numeric/audio-library versions. Raw hearing identity binds waveform bytes,
  actual device, model/weights, worker/environment, and decode settings; glossary
  names remain an assessment input because these hearings use no glossary prompt.
  Ranking weights/counts do not invalidate raw evidence.
- `tests/test_hardening.py`: focused lifecycle, recovery, cache, and stop-before-
  finalization regressions. No production provider, generation, orchestration,
  source-resolution, segmentation, comparison-export, or supervisor code changed.

### Focused regression results

Final run: **56 tests, 55 passed, one skipped, zero failures**, in 1.293 seconds.
The skipped pre-existing recorded-speaker test lacks its optional reference/cache
fixture. All new regressions ran. The test fixture that forces a verification
failure intentionally prints `STATE failed`; this is an asserted safe stop, not
a failed test.

The selected classes/cases were `WorkerTests`, `VerificationIdentityTests`,
`AsrEvidenceTests`, the three existing shutdown/timeout worker regressions,
`SequenceCheckTests`, `SelectionTests`, `SpeakerTests`,
`VerificationTimeoutIdentityTests`, `VocalEventTests`, and
`PerformanceTimingTests`. Fake worker/cache checks passed before real ASR was run.
The isolated `bin/aidub --config config/batch1.local.json --help` also loaded
successfully using the configured shared interpreter. Imports were explicitly
bound to the isolated checkout; bytecode writes were disabled during verification.

The regression receipt is local and ignored:
`jobs/.batch1-eval/final-focused-tests.log`. Tests used fake workers and temporary
fixtures; no real provider or Qwen synthesis was exercised.

### Existing-WAV check: fresh execution versus reuse

Six existing WAVs were read: selected raw takes for cues 1, 3, 30 (a short
reaction), and 154 (previously affected), plus processed takes for cues 3 and 154.
No source or take bytes were changed. All six assessments completed and passed
the unchanged checks. None required a second hearing; second-hearing failure and
recovery were covered by fake-worker/cache regressions, not a claimed live result.

| Measured operation | Result |
| --- | --- |
| One fresh CUDA Whisper worker startup | 4.994 s to readiness |
| First inference request after startup | 1.956 s |
| Subsequent five requests on the loaded worker | 0.261–0.322 s each |
| Fresh six-WAV verification loop | 8.684 s, including startup, inference, analysis, and cache writes; excluding receipt setup and initial identity/version inspection |
| Warm six-assessment reuse | About 0.002 s; zero ASR calls |
| Changed ranking weights/counts | Six assessment-cache hits; zero ASR calls |
| Assessment-only recomputation from stored evidence | Six hearing hits and six waveform-fact hits; zero ASR calls; original decisions retained |

The worker, weights, and decoding options were the existing configured Whisper
Turbo setup. Only one worker was started and it was reaped. No live CPU fallback
or host/GPU fault was induced. These small timings are observations, not a
whole-video speed forecast or a cold-versus-warm speedup claim. Processed audio
passing technical checks is not human listening or voice-identity approval.

Local ignored evidence is under `jobs/.batch1-eval/`:
`existing-wavs-receipt.local.json`, `existing-wavs-console.local.log`,
`final-replay-receipt.local.json`, and `final-reassessment.local.json`. The last
two bind final source hashes/implementation and check reuse without another
model request. The final code's additional cache-environment binding was checked
by replaying retained hearing evidence, without another cold model run.

### Zero-call and preservation evidence

The existing-WAV harness disabled both provider roles in ignored evaluation config,
guarded provider entry points and Qwen synthesis/backend entry points, and allowed
subprocesses only for the configured Whisper worker or package-version inspection.
Its counters report **zero provider calls and zero fresh Qwen synthesis**. The
only fresh model work was six local Whisper requests. Final replay additionally
forbade `_LineAssessor._transcribe` and recorded zero fresh ASR requests.

Before/after signatures of all source-job and overnight-record file names,
sizes, and mtimes matched. Byte hashes of the six input WAVs matched, and hashes
of protected manifest/config/validation files and transferred operational recovery
files were unchanged. No FFmpeg/export, source-job runner, provider adapter, or
supervisor was launched. No merge or push was performed.

### Compatibility, rollback, and remaining limits

Synthesis keys and WAV bytes are unchanged. New hearing/fact records use
`aidub.hearing.v1` and `aidub.waveform.v1`; assessments have a versioned identity
and explicit completeness fields. Old quality records are retained but are not
silently promoted into the new identity: their missing evidence provenance cannot
be reconstructed safely. On a future authorized migration, legacy WAVs are
reverified on demand without synthesis. That first-migration cost has not been
measured over a long job. Subsequent ranking changes reuse evidence.

Changed model/weights/decoding/device invalidates relevant hearing identities;
changed assessment thresholds/names/reference recomputes assessment using sufficient
stored raw evidence. Incompatible waveform-analysis inputs recompute facts.
Existing schedule/downstream fingerprints incorporate the new verification identity.
No existing job configuration or cache was migrated during this work. Rollback
uses the retained recovery baseline and old records; do not delete either cache
generation or treat new assessments as compatible with old code.

Exhausted hearing identities stop without automatic budget reset on resume. An
unreaped-worker marker remains blocking across resume until ownership is resolved;
this batch adds no administrative reset command or reboot/orphan reconciliation.
The real check did not exercise concurrent resident Qwen/Whisper, CPU latency,
reboots, long-job throughput, or every possible follow-up/prefix outcome. These
remain limits, not passes. At batch-1 completion, batches 2–6 and adaptive
candidate reduction remained unimplemented. Batch 2 was subsequently authorized;
its completion evidence follows. Batches 3–6 still require authorization.

## Batch 2 completion evidence — 2026-10-16

### Isolation and scope

Continued in `ai-dubbing-e2e-asr-batch1` on branch
`fix/asr-correctness-20261016`, directly from batch-1 evidence commit `74b9cc9`
and implementation `17d23353372cf19ab02def3555bc6e37e40706f1`; recovery baseline
remains `418f205b968e66bd1511a9a1cdfd321263328be6`. Batch 2 is committed
separately as `fb66b11a1f1396aba3f65c5057ca9587877314a5`; this plan's evidence
update follows it in a documentation-only commit. No branch switch, merge, push, installation, environment migration or
operational-job invocation was performed.

The isolated tree was clean before development. Read-only process checks found
no dubbing/ASR/overnight worker. Operational Git status/diff and the long-job and
overnight artifact-tree metadata signatures were captured in an ignored local
receipt, then compared after verification. No operational job lock was acquired.
All test job writes and locks used disposable temporary directories. Test logs
and preservation receipts are ignored under `jobs/.batch2-eval/`.

### Changed behavior

- `aidub/pipeline.py`, `aidub/job.py`, `aidub/unattended.py`: for source-events
  jobs, pending exact-text compact review now returns exit 2 in the explicit
  `awaiting_repair_review` state before scheduling, synthesis, mix, export,
  validation or risk reporting. Auto completes this handoff under its existing
  owned lock, then calls `run_job` with that same lock. The old post-partial
  review/re-finalization loop is removed.
- `aidub/fidelity.py`, `aidub/quality_flow.py`: one small pending-review selector
  is shared by orchestration and execution. It retains the existing policy for
  historical jobs and explicit `leave_unresolved` decisions. Checked text and
  disputed/revised-unconfirmed blockers are unchanged. Final-round revisions are
  still unconfirmed; resume cannot automatically grant them additional rounds.
- `aidub/review.py`: disputed-line back-translation is requested only before a
  following bilingual review round. Required earlier evidence still reaches that
  next round. Final text, round bounds and review status rules are unchanged.
- `scripts/overnight.py`: the new state is classified alongside existing provider
  handoffs. This is a compatibility addition; worker supervision, provider
  fallback policy and process retry budgets were not redesigned.
- `docs/architecture.md`: documents the state and manual/auto behavior.

Manual `run`/`resume` stops with a clear hint and never calls providers. Continue
that handoff using configured `auto` with the original video/name. Disabled
review leaves it blocked. This batch does not add a manual bilingual-review
response acceptance command; existing translation and compact-repair JSON
handoffs remain unchanged. Completed disputed/unconfirmed reviews can still
produce an explicitly partial output with their lines unvoiced, preserving the
existing fidelity policy.

### Focused verification

Executed with the configured shared Python interpreter and explicit isolated
checkout/test import paths; no historical aidub implementation was imported.
The initial 10-case focused run passed. The expanded regression run passed
**22 tests** in **0.968 seconds**, with a final repeat passing in **0.947 seconds**
(test runtime, not pipeline performance):

```text
test_batch2
test_quality.ReviewTests
test_hardening.ProviderRecoveryTests
test_performance.PerformanceTimingTests.test_compact_repair_verdict_is_bound_to_the_actual_repaired_text
test_performance.PerformanceTimingTests.test_disputed_source_is_not_spoken_or_loaded_for_synthesis
test_core.TranslationFingerprintTests
```

`tests/test_batch2.py` uses the saved JSON fixture
`tests/fixtures/compact_repair_review.json`, real request validation, batching,
atomic response/attempt persistence and orchestration, with provider/media stages
replaced by fakes. Evidence includes:

- Review → review confirmation → schedule → mix → validate ordering. The
  scheduler sees exactly `Hope it hasn't seen me.`, with a matching checked-text
  verdict, rather than the superseded compact wording.
- Manual resume and disabled-review auto stop before schedule/media/provider work.
  The owned lock excludes a second holder during review; existing subprocess
  fake-provider lock-exclusion checks also pass.
- Accepted resume makes zero additional fake provider calls. An interruption
  immediately before timeline acceptance replays both matching cached responses
  without new attempts. An exhausted later-round attempt stays exhausted across
  resume while the earlier accepted response is reused. Compact-revision history
  is not replenished and a further repair at its limit is rejected.
- Disputed and revised-unconfirmed fixtures remain blocked/partial across
  resume. No second review cycle is granted to make them pass.
- Review budgets of 1, 2 and 4 rounds request respectively 0, 1 and 3
  back-translations when every round remains disputed; each earlier rendering is
  present in the following review request. The final rendering is omitted and
  disputed status remains unchanged.

**Live provider calls: 0. Fresh Qwen synthesis: 0. Media exports: 0.** New tests
guard synthesis/backend/ASR/media execution. The existing provider recovery suite
uses local fake commands or patched provider functions only. Media stages are
mocked and no source clip or existing WAV evaluation was run. No batch-1 model
evaluation was repeated. These tests establish control flow and cache behavior,
not listening quality or long-job runtime improvement.

### Cache compatibility, migration and rollback

No config defaults, provider identities, request schemas, request contents,
batch paths, accepted-response identities, raw hearing/waveform evidence,
assessment keys or synthesis keys change. Matching saved review responses and
their persisted attempt budgets remain reusable. Review audit metadata records
`decision_policy=back_translation_before_next_round_v1`; compact-review audits
also record `orchestration_policy=compact_review_before_schedule_v1`. These
markers are outside provider requests and do not invalidate paid responses.
Old final-round back-translations are retained; their absence in new audits is
expected and does not invalidate a review.

No existing job migration was executed. On future authorized use, an old partial
job with unreviewed compact text stops at the new handoff before reusing exports.
An already exact-text-reviewed job needs no extra review. As before, accepting a
changed review invalidates schedule/mix/validate; downstream keys bind current
English and its verdict. Unchanged takes and raw verification evidence remain
reusable. Existing snapshots without source-events keep the historical policy.

Rollback is the batch-1 tip `74b9cc9` in a separate stopped checkout, with job
snapshots/history retained. Old code lacks the new handoff but its run entry
resets state before following its previous flow; do not delete locks, responses,
jobs or caches to roll back. Do not mix old/new runners on the same job.

### Limits and next-batch gate

There is no measured whole-video speedup. The change removes one unused call
only when the last round is disputed and avoids the prior pre-review
finalization pass; savings depend on the recording. The 4–7 h and 2–4 h targets
remain hypotheses. Provider latency, audio quality and full media validation
were not evaluated in batch 2. Existing outer handoff-round accounting and
provider metrics retain their earlier scopes; this batch adds no general
durable orchestration budget or metrics redesign.

Focused control-flow/cache/lock evidence supports moving to a separately
authorized batch 3. Luna hardening/configuration, optional comparison export,
automatic uncertainty resolution, concurrency and candidate reduction have not
been implemented. Preserve the accepted reference and voice settings for any
future model/audio comparisons.

## Exact scope of the first implementation batch

Batch 1 is limited to `aidub/asr_client.py`, `aidub/verification.py`, ASR assessment,
recovery, and completeness gates in `aidub/pipeline.py`, and the smallest necessary
assessment/ranking separation in `aidub/quality.py` or `aidub/selection.py`. Extend
focused cases in the existing hardening/performance test modules. Use existing
atomic/cache helpers; add no new worker protocol, provider executor, public job
state, or general tracing/cache framework.

Deliver original-error preservation with safe process ownership, explicit incomplete
second hearings, persisted bounded recovery, identity that retains glossary names
and effective assessment inputs, and reuse of sufficient hearing/waveform evidence
when only ranking changes. Required proof is fake-worker/cache regression results
plus the at-most-eight-existing-WAV local-ASR receipt, with zero provider calls and
zero synthesis. Preserve all voice settings and required gates. Do not change
orchestration, provider configuration, comparison export, source decisions,
segmentation, candidate budgets, the supervisor, or any existing job/config artifact
in this batch. Batch 1 is implemented and verified only in the isolated worktree,
with the completion evidence above; it has not been integrated into operation.
