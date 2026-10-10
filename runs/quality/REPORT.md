# Quality preset — short-sample before/after (2026-10-10)

Source: the listened-to 81.7 s sample `base-video.mp4` (mixed 0, game 1, mic 2). Same config, Cursor command provider, Whisper turbo weights, Qwen 1.7B English ICL with reference B, generation settings, trim rule and max tempo 1.10 in both runs. Paths are relative to the checkout; media and logs are ignored by Git.

| | Baseline | Quality preset |
| --- | --- | --- |
| Job | `jobs/quality-baseline-20261010` (fresh run of `harden-unattended` `beff721`) | `jobs/quality-preset-20261010b` |
| Command | `bin/aidub auto … --name quality-baseline-20261010` | `bin/aidub auto … --name quality-preset-20261010b --preset quality` |
| Status | partial (`source_energy_accounted`) | complete, all required checks passed |
| Cues / placed | 26 / 26 | 25 / 25 |
| Overlapping duplicate source cues | 1 (ids 25/26, "Espero que por acá" twice) | 0 |
| Voiced gaps without text | 6, unreviewed | 6 re-heard: 1 recovered ("adentro"), 5 unintelligible and not voiced |
| Median / p90 English syllables per second of chosen takes | 5.87 / 8.20 | 5.23 / 6.85 |
| Mean / max English end past Spanish end | 0.172 / 0.715 s | 0.205 / 0.950 s |
| Tempo-adjusted lines with loudness match and margins | 0 of 0 | 1 of 1 (id 14, tempo 1.022) |
| Takes generated / rejected | 34 | 102 / 2 (`abnormal_rate`, `wrong_speaker`) |
| Provider calls | 1 translation | 1 context, 1 translation, 2 review rounds, 1 back-translation |

These are technical measurements. Neither run has a listening approval, and lower syllable rates or a complete status do not prove natural speech.

## Line changes worth listening to

| Spanish | Baseline English | Quality English |
| --- | --- | --- |
| Que se convierten | That turn into… | and they transform. |
| Ok, trato de esquivar un poco, esquivado | Okay, I'll try to dodge a bit, dodged | Okay, I'm trying to dodge a little… dodged! |
| Casi me mata un perro … Me voy a comer este huevo (×2) | split across two cues, the egg line voiced in both | one take; the repetition was heard twice by the second pass and kept |
| (Sí,) estamos completamente / llenos en cuanto a la salud | If we're completely full on health | So now we're completely full / as far as health goes. |
| Estamos dentro … ahora sí adentro | two takes; first-pass ASR had dropped "Adentro" as near-silence | one take; "adentro" recovered from voiced energy by the second hearing |
| Espero/Pero que por acá | Hopefully over here (voiced twice) | but she's around here somewhere. — disputed, see below |

Excerpts (Spanish mic, baseline mix, quality mix at the same timestamps) and 720p previews are in `runs/quality/comparison-20261010/` (`COMPARISON.md`, `excerpts/`, `previews/`). The quality job's own ranked list is `jobs/quality-preset-20261010b/report/risk.md` with `report/excerpts/` and `report/previews/`.

## Findings during the run

- **Tempo path.** Confirmed in code and on real output: the previous assembler gave tempo-adjusted takes only an 8 ms safety fade, with no loudness match and no margins. `presentation_version=2` now processes every take identically; regression `PresentationTests.test_tempo_take_gets_same_margins_and_gain_as_other_takes`.
- **Trim evidence.** With adaptive margins (floor RMS 0.0015), 3 of 25 chosen takes kept low-level decay beyond the former fixed 60 ms tail, up to 98 ms (id 4). The fit-measurement trim rule itself is unchanged.
- **Voseo.** An earlier interrupted run (`jobs/quality-preset-20261010`, stopped before synthesis; kept as evidence) read "Morí de una vez, che" as "I died" in the context summary and produced "Dead just like that, man." General voseo guidance was added to the context, translation and review prompts; the final run gives "Just die already, man!", as the baseline did.
- **Gap overlap.** The same interrupted run recovered words already inside the end of neighbouring cues ("puertas", "adentro"), because voiced-gap spans include covered parts of an energy run. The second pass now only listens to the uncovered part and refuses text that repeats a neighbour; regression `test_gap_overlapping_a_cue_does_not_duplicate_its_words`.
- **Text-check strictness.** "and they transfer" initially matched "and they transform" under a two-edit spelling tolerance. Tolerance is now one edit (two only for names). The finished job was re-verified under the final checker by resuming it: 0 new syntheses, 102 cache hits, 102 ASR checks, 3 second verifications, no provider call, same selected takes. The pre-fix result is kept in `runs/quality/b-first-completion/`.
- **Decoding change is mixed.** Beam search without previous-text conditioning removed the duplicated cue but heard "Pero que por acá" where the baseline heard "Espero que por acá" (probably correct), so the translation lost "I hope". The reviewer marked it disputed and requested back-translation; it is the top item in the risk report. It was not changed automatically.
- **Loudness floor.** Several takes hit the existing 0.6 minimum gain of loudness matching, so for quieter cues the −dB source-loudness cue is partly clipped.

## Whisper large-v3

Not evaluated: only `large-v3-turbo.pt` exists locally. `bin/aidub asr-compare quality-preset-20261010b --models turbo,large-v3` refuses and reports that `large-v3.pt` (about 2.9 GB) would have to be provisioned. Nothing was downloaded.

## Automated checks

`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. <qwen-env>/bin/python -m unittest discover -s tests -v`: see the commit message for the count. New coverage in `tests/test_quality.py`: sequence checks (contractions, numbers, negation/name/number loss, repetition, reordering, truncation, short reactions, babble, wrong language), context glossary validation, utterance grouping and joins, legacy request identity, review validation/rounds/back-translation/audit, provider aliases and preset merging, second-pass duplicates/recovery/unintelligible/overlap, best-of-N ranking and bounded extra attempts, pacing gates, adaptive margins, unified tempo presentation, bounded source loudness, and a fake-model/fake-provider quality-preset auto run with cached resume.
