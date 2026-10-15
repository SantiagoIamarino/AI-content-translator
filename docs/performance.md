# Conversational performance

This work follows the audit of `f82d286` and the user's observation of a sustained
thinking sound near 00:10. The approved relaxed reference, its transcript, Qwen
generation settings, English ICL, trim measurement (RMS 0.005 / 10 ms / pad 0),
maximum tempo 1.10, continuous game bed and copied video remain fixed.

Use `--preset performance` for an explicitly configured new job. Existing jobs
retain their configuration snapshots; do not point a new experiment at an old
job name in the same jobs directory. Implementation checkpoints and exact recovery
steps are in [performance-progress.md](performance-progress.md).

## Demonstrated problems addressed

- Duplicate filtering could discard “este candado” at 44:12 of the longer recording
  when the later phrase “A ver este candado” shared a prefix with “A ver”. The longer
  phrase now survives; ambiguous evidence preserves unique words. Energy coverage
  is recomputed after filtering, so a removed cue's region is not silently hidden.
  Matching text several seconds later cannot close a timed connector gap; source
  word timestamps must support nearby coverage. Final coverage is refreshed again
  after joining and event realization.
- Broad cue coverage hid the thinking sound near 00:10. Whisper emitted no filler,
  and gap recovery examined only the small region before the next cue. Timed
  source events now exist independently of lexical cue coverage. A leading
  confirmed hesitation can be a required prefix of the connected thought, rather
  than an isolated take constrained by an approximate internal Whisper boundary.
- A matching take could fail solely for a pause over one second. A contextual
  check now distinguishes a source-supported thinking pause from an unsupported
  generated pause, using approximate position and duration. Other quality failures
  are retained. Raw verification remains separately cached and auditable.
- The bounded tail scan could miss a delayed or softer generated release. The new
  preset inspects the complete tail within a two-second analysis limit, protects
  decay down to RMS 0.0001, and refuses a window that would cut protected signal.
  An unsettled raw endpoint still requires another take. A longer fade is not a
  substitute for missing audio. Tempo takes are checked again after processing.

## Source events and uncertainty

`transcribe/vocal_events.json` binds the event ledger to the microphone WAV hash.
It records kind, source interval, provenance, confidence status, disposition and
cue ID. `report/vocal_events.json` adds English and actual placement. Events can
be represented even when Whisper emits no word. This is not microphone passthrough.

A local annotation file may supply confirmed listening evidence:

```json
{
  "schema": "aidub.source_events.v1",
  "mic_sha256": "SHA256_OF_EXTRACTED_MIC_WAV",
  "events": [{
    "id": "thinking-0010",
    "start": 10.178979,
    "end": 10.72,
    "kind": "hesitation",
    "status": "confirmed",
    "provenance": "user_listening",
    "evidence": "User identified the hesitation; boundaries are approximate.",
    "realization": "Uh..."
  }]
}
```

Set `source_events.annotations_file` in the stopped experimental job or local
configuration. The supplied microphone hash must match. Annotation text is data;
it cannot supply arbitrary English instructions. Supported hesitation realizations
are `Uh...`, `Um...`, and `Hmm...`. Events conflicting with recognized words remain
unresolved; text is not erased to make room. Cue splitting requires reconciliation
of every existing word. Existing lexical IDs are retained where possible.

The 00:10 annotation uses the user's listening identification. Its onset follows
the measured acoustic run and its end follows the saved first lexical onset;
neither boundary is claimed to be a listened-to or forced-aligned boundary.
The performance preset uses `source_events.realization_mode=prefix_with_following`
for a leading annotated hesitation. Its event interval remains in the ledger; the
connected take starts at the event onset and must contain the required English
prefix in both raw and processed verification. Precise internal event duration is
not claimed from this check. Separate units remain supported for other events.

Full-sentence Whisper can normalize away a generated filler. In the actual minute
tests, raw seeds 1044 and 5044 gave no `Uh` in full-sentence ASR, but their 0.55-,
0.8- and 1.1-second prefix excerpts consistently returned `Uh`. The verifier now
requires agreeing focused windows when the full reading omits the prefix, with
no expected-text prompt. These are narrower hearings using the same model, not
independent recognizers. Low word confidence remains explicit and raises listening
priority. Raw and processed prefix checks have separate waveform-bound caches.

Isolated source-ASR hesitations carry their ASR provenance. A conservative
periodicity scan can nominate unexplained regions inside broad cues, but those
regions remain **unknown** and cannot generate speech. Periodicity and energy
cannot distinguish speech conclusively from all noises. Silence, noise and breaths
never authorize English words. Laugh/sigh realization and original microphone
passthrough remain unvalidated; confirmed events of those kinds remain unresolved.

Translation and bilingual review receive the event ledger and approximate source
pauses. They preserve the function of fillers, connectors, restarts and small
reactions, without adding excitement or reconstructing ambiguous words from game
knowledge. A fixed event realization cannot be changed by translation or review.
Filler-only generated lines require a heard vocal event and cannot pass an empty
normalized-text comparison. This does not guarantee recognition of every filler
inside a longer sentence.

Materially opposite ASR polarity readings of shared content (the longer job's
“ya es suficiente” versus “aún no es suficiente”) are explicitly withheld from
synthesis pending source resolution. Context cannot choose one for unattended
voicing. The checker is conservative and limited; it does not adjudicate arbitrary
semantic differences. Nonmaterial disagreements remain available to bilingual
review and visible in the partial-status report. Performance jobs also withhold
lines whose final review remains disputed or whose last revision lacks a confirming
review. A plausible written translation does not establish what ambiguous audio
said. Those cues remain retained/translated but explicitly unplaced; no model is
loaded to synthesize them. This deliberately favors an honest partial preview over
speaking an unresolved reading.

Compact timing repairs also need bilingual review of their **current text**.
An earlier translation verdict cannot approve a later rewrite such as changing
`it hasn't seen me` to `I'm not seen`. Performance scheduling withholds repaired
wording until a text-bound verdict exists. Configured unattended runs perform
bounded review/back-translation using the same configured roles, retain exact
requests/responses and audits under `handoff/repair_reviews/`, then resume without
reacquiring the owned job lock. Disputed or unconfirmed revisions stay unvoiced.
Manual runs can remain partial until the configured unattended review runs.

New gap words require a concordant timed hearing with neighboring acoustic
context (`asr_second_pass.confirm_recovered`). The repetition fixture exposed a
single-window `¡Gracias!` with a 20-ms word timestamp and probability 0.65. That is
not listening evidence for a recovered word. The extra context hearing has no
expected-text prompt, retains its evidence, and cannot turn an unsupported reading
into a cue. Matching original hearing windows retain their cache identities.

## Pauses, grouping and endings

Source pauses are low-energy microphone intervals inside a cue, measured in
bounded memory and explicitly marked approximate. They are evidence for rhythm,
not word recognition. Candidate pauses are matched conservatively by normalized
position and duration. Matching evidence can resolve a global pause rejection;
it cannot resolve a speaker, content, number or negation failure. Selection also
penalizes missing source pauses and unsupported generated pauses.

The preset protects isolated reactions from short-gap joining and unrelated
translation groups. Joined cues retain their source spans and measured pauses.
It does not indiscriminately expand the synthesis-unit limit, shift later lines,
overlap takes, stretch video, or slow every English utterance to the Spanish span.
The source-duration score chooses among takes, with the existing hard rate bound.
If the initial valid pool has no placeable take, `search_for_placeable` uses its
remaining bounded attempts. Vocal events and required prefixes cannot be shifted
earlier or sent for meaningless compact rewrites just to achieve placement.
Performance reactions also cannot use the early-start fallback in either take
collector; a failed fit does not authorize reacting before the gameplay event.

Full-tail inspection protects generated signal across quiet dips and below the
ordinary core threshold. Fades remain outside protected signal; raw truncation,
analysis-bound exhaustion, insufficient room and unsettled processed endpoints
reject a take. Source/target word correctness and natural decay still require
listening; a settled endpoint alone is not a phoneme guarantee.

If a preceding take ends at the next source anchor, a protected generated lead
can use up to 80 ms of local slack inside its own window. The core is delayed only
by the required lead budget; no later anchor moves. All protected samples and the
next boundary still have to fit. The actual delay is reported in presentation
metadata. This fixes rejection of otherwise fitting takes solely for insufficient
preroll, without allowing overlaps or cutting a valid lead.

## Technical status and resume

Performance jobs require explicit event placement and resolution of unintelligible
source gaps or disputed/unconfirmed bilingual reviews. Those conditions produce
partial status with reports; they are not silently accepted because an ASR pass
or review finished. `report/source_uncertainties.json` retains exact intervals and
texts. The old reviewed-gap policy remains available in historical snapshots.

Source analysis changes invalidate dependent transcription/translation stages but
reuse matching raw Whisper windows and saved second hearings. Request identities
retain context and event metadata; mismatching provider responses are not reused.
Generation keys remain unchanged for identical text, seed and reference settings.
Contextual pause decisions are separate from raw take verification. Processing and
selection identities include their implementation and settings. Validation-only
changes reuse completed analysis, provider responses and raw takes.

## Evaluation tools

`scripts/continuity-evidence.py --preset performance` renders a cached-take
comparison without providers, synthesis or new ASR. It rechecks saved ASR, records
same-take processing separately from reselection, and never accepts a job.

`scripts/performance-evaluate.py prepare` creates a bounded isolated passage from
an existing job's extracted tracks and available copied picture. Supply the
approved reference configuration explicitly. A missing original recording remains
a validation limitation. Fixtures preserve copied video packets and game samples;
stream-copy seeks can include keyframe preroll, so WAV boundaries are authoritative.

Run each prepared source with this checkout's `bin/aidub auto`, using the saved
local configuration, source and name from `passage.json`. `run-set` serializes those
commands, retains per-job logs and checkpoints `queue/state.json` after each job.
It holds a separate queue lock and passes normal work through the existing CLI.
`render` creates original Spanish / prior English / new English video and voice
comparisons, plus cue and event accounting. These are experimental listening
artifacts, not perceptual approval.

`excerpts --output PASSAGE --start A --end B` creates short three-way comparisons
using absolute original recording times. Their voice/mix WAVs have exact requested
sample boundaries. The videos preserve MP4 edit-list preroll and compare their
first displayed frame with the requested source frame.

The initial Matroska passage fixtures normalized copied keyframe preroll: for the
600-second passage, the first packet was from 598.55 seconds but displayed at
zero alongside samples from 600 seconds. This was an evaluation-tool error, not a
change to production extraction. Existing fixtures/jobs are preserved for audit;
their pipeline exports do not establish absolute picture alignment. The corrected
comparison renderer copies directly from the full available baseline picture,
preserves the MP4 seek origin, and checks the first displayed frame after mux.
New fixture preparation instead aligns every audio crop to the actual copied
keyframe, records requested and actual intervals, and checks its displayed origin
before ASR or providers. It refuses a mismatch.

Completed results, exact cue/event accounting, listening paths, cached/fresh
comparisons and remaining limitations are in [performance-results.md](performance-results.md).
No full-length soak run or general automatic filler-recovery guarantee is claimed.
