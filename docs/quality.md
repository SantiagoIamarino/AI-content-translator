# Quality preset

`--preset quality` overlays `config/presets/quality.json` onto the selected config when a job is created. The job snapshot stores the merged result, so later edits to the preset do not change existing jobs. Jobs created without the preset, and every existing job, keep their previous behaviour and request identities.

```bash
bin/aidub auto /absolute/path/recording.mp4 --name NAME \
  --mic-ordinal 2 --game-ordinal 1 --mixed-ordinal 0 --preset quality
# Repeat the same command to resume.
```

Unchanged on purpose: Qwen 1.7B Base, English ICL (`x_vector_only_mode=false`), reference B and its transcript, the generation settings, trim RMS 0.005 / 10 ms / pad 0 for fit measurement, and max tempo 1.10.

## What the preset adds

| Stage | Behaviour | Evidence |
| --- | --- | --- |
| Source ASR | Whisper decodes with `condition_on_previous_text=false`, beam 5 (`whisper.decode_options`). | `transcribe/chunks/` |
| Second hearing | A separate Whisper worker re-hears cues with low-confidence words, adjacent cues that repeat each other, and voiced spans without text. A repeat heard once is removed; heard twice it is kept as real repetition. A voiced gap becomes a cue only with confident words inside the uncovered part of the gap that do not repeat a neighbouring cue. Otherwise it is classified (`unintelligible`, `no_speech_heard`, `non_speech_energy`, `covered_by_existing_cue`, `already_transcribed`) and never filled by guessing. Differing readings of uncertain cues are passed to translation as `asr_alternatives`; the first-pass Spanish is kept. | `transcribe/second_pass.json`, `transcribe/corrections.json` |
| Utterances | Cues separated by ≤0.35 s are joined into one take (`source_cues` keeps the original spans). Longer open-sentence pauses (≤1.5 s) are grouped for translation by `utterance_id` but voiced separately. | `transcribe/corrections.json` (`utterance_join`) |
| Context | One provider call per transcript part produces a summary, register, glossary and style notes, from the transcript only. Glossary terms must occur in the transcript or the response is rejected. | `handoff/context/context.json` |
| Translation | Every batch carries the global context, three neighbours on each side, utterance ids, soft `target_syllables` (5.0 English syllables/s at tempo 1.0) and `max_syllables` (window × 1.10). | `handoff/translation_request.json` |
| Review | A separate bilingual review compares Spanish with English and revises meaning errors, omissions, additions, negations, numbers, names, terminology, unnatural phrasing, fragments and over-long lines. Round 1 reviews every line; later rounds re-check revised or disputed lines only (`max_rounds=2`). Back-translation (English→Spanish, without the source) is requested only for disputed lines and passed to the next round as evidence. | `handoff/translation_audit.json`, timeline `translation_review` |
| Voice takes | Best-of-N: 4 valid takes per line (up to 4 extra seeds replace failed takes). Hard rejections: material text errors, repetitions, truncation, clipping, pathological internal pauses (>1.0 s), implausible speaking rate, and the existing pitch+brightness wrong-voice proxy. Valid placeable takes are ranked by pacing (rate band 3.8–6.5 syll/s, long pauses), ASR agreement and confidence, distance from reference B and from takes already chosen in this job, then tempo. | `schedule/summary.json` `selection_summary`, `ledger/` |
| Text check | `sequence-v1` aligns intended English with ASR of the take. Contractions, numbers, fillers, plurals and small spellings are tolerated. Lost or flipped negations, numbers and names, missing/extra content, back-to-back repetition, reordering and truncation are reported. Soft differences get one second hearing with English forced and beam search. Hard issues reject; a remaining soft difference is kept but penalised and flagged. Short reactions are judged leniently. | `cache/quality/`, `quality.text_check` |
| Presentation | Every selected take, including tempo-adjusted ones, receives the same processing: adaptive quiet margins (base 20/60 ms, extended while the signal stays above RMS 0.0015, up to 80/200 ms), loudness matching, then tempo, then the window bound. A bounded source-loudness cue (half the cue's voiced-mic level difference from the job median, clipped to ±3 dB) adjusts the loudness target. | `presentation`, `schedule/source_loudness.json` |
| Risk report | Lines and voiced gaps ranked by review status, ASR doubts, selection evidence, tempo and budget, with Spanish mic / English voice / mix excerpts and 720p previews for the top items. | `report/risk.md`, `report/excerpts/`, `report/previews/` |

Additional validation gates for preset jobs: `translation_reviewed` (each line has a review record), `presentation_consistent` (each placed take went through the unified path), and `source_energy_accounted` under `untranscribed_energy_policy=reviewed` (every voiced gap was re-heard and classified). The risk report is evidence for listening, not an approval or a repair queue.

## Providers

The preset maps the new roles explicitly onto configured providers:

```json
"providers": {
  "context": {"kind": "same_as", "role": "translation"},
  "review": {"kind": "same_as", "role": "repair"},
  "back_translation": {"kind": "same_as", "role": "repair"}
}
```

Replace an alias with a full provider spec to use a different model for review. There is no implicit fallback; an alias to an unconfigured role fails before any call. Each role has its own schema validator, bounded attempts and saved request/response under `handoff/batches/<role>/` or `handoff/context/`.

## Whisper models

`asr_second_pass.model` defaults to `turbo`, the only Whisper weights present on the development workstation. `large-v3` is configurable (`asr_second_pass.model` or `model_path`) but is not assumed to be better. Compare on a finished job:

```bash
bin/aidub asr-compare JOB --models turbo,large-v3
```

It writes `report/asr_compare.md` with per-window agreement and mean word probability. It refuses to run when any model's weights are missing and reports the download that would be needed (large-v3 is about 2.9 GB); aidub never downloads models.

## Existing jobs

Jobs without the preset keep their transcript fingerprints and translation request identities, so saved translations are reused. Because candidate-checker sources (`quality.py`, `audio.py`, `asr_worker.py`) changed on this branch, resuming an older job reruns candidate verification once; synthesis caches are reused and the legacy text checker and presentation path still apply to its snapshot.

## Limits

- All checks are proxies. ASR agreement, pitch/brightness distance and syllable rates do not prove that a line sounds natural or that the voice is recognisable.
- The speaker proxy is not a speaker embedding. No embedding checker is installed; one may be added later as an optional, calibrated signal, never as a hard gate for short cross-language phrases.
- Review quality depends on the configured model. The audit trail shows every revision and reason.
- The second hearing uses the same turbo weights with different decoding and a narrower window; it is a consistency check, not an independent model.
- Laughter/scream passthrough from the original mic is deferred.
