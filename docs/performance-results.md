# Conversational performance results — 2026-10-15

Implementation starts from `f82d286` on the existing isolated development branch
`fix/conversational-continuity-20261015`; `297f406` and the saved original outputs
remain the earlier baseline. No merge or push was performed.

**The agent cannot listen to this audio.** These are source/target text, ASR,
waveform, cache, placement and media checks. No perceptual approval is claimed.
All nine fresh experimental jobs remain **partial**, with their unresolved source
readings and withheld cues visible. Reduced silence is not an approval criterion.

## Listen here

The local comparison hub is `runs/performance-20261015/index.html`. Every passage
has original Spanish, prior English, new English, voice-only WAVs, absolute source
timestamps, source/target text, placement status and linked machine accounting.

| Listening comparison | Local path under `runs/performance-20261015/` |
| --- | --- |
| Final minute preview | `jobs/minute-tranquila-corregida-20261014/output/english_PARTIAL.mp4` |
| Minute, all three versions | `minute/index.html` |
| 00:08–00:14, thinking sound | `minute/excerpts/00008.000-00014.000/index.html` |
| 00:21–00:34, connectors and shorter English | `minute/excerpts/00021.000-00034.000/index.html` |
| 00:34–00:44, relaxed delivery and ending | `minute/excerpts/00034.000-00044.000/index.html` |
| 00:44–00:58, repetition and remaining tail gap | `minute/excerpts/00044.000-00058.000/index.html` |
| 10:00–13:10, representative longer passage | `long-600-790/index.html` |
| 10:49–10:56, short reactions | `long-600-790/excerpts/00649.000-00656.000/index.html` |
| 11:18–11:26, generated ending and available room | `long-600-790/excerpts/00678.000-00686.000/index.html` |
| 11:43–11:50, repeated “Intentar” | `long-600-790/excerpts/00703.000-00710.000/index.html` |
| 44:08–44:16, “este candado” | `candado-2648-2656/excerpts/02648.000-02656.000/index.html` |

Other short comparisons cover 01:14–01:18, 14:02–14:12, 15:48–15:52,
32:06–32:16, 36:20–36:26 and 42:20–42:34. Together the nine passages cover
about **5:06 of unique source material**. The hub links all of them.

## Demonstrated changes

| Original time | Evidence and result |
| --- | --- |
| 00:10.179–00:10.720 | The user identified the sustained thinking sound. Original Whisper emitted no filler; broad cue coverage hid it from gap recovery. A microphone-hash-bound event now reaches translation as a required `Uh...` prefix of the following thought. Full-sentence ASR normalizes it away; distinct unprompted prefix windows corroborate it in raw and processed audio, at low confidence. It is placed with cue 2, starting at 10.113 s including the protected lead. Internal vowel duration/alignment is approximate. `minute` event reports, `prefix-probe/results.json`. |
| 44:11–44:13 | Original duplicate review heard `A ver este candado` once but deleted the entire longer cue, losing `este candado`. The corrected branch preserves unique suffix words and recomputes coverage from surviving cues. `candado-replay/evidence.json` repeats the exact saved hearing and original spans with no new ASR/provider/TTS: the full phrase survives. Fresh English says **“Let's see this padlock.”** Its cue spans 44:10.179–44:13.211 under the cropped ASR, which differs from full-recording timing; exact internal word timing needs listening. |
| 11:19.690–11:25.019 | The same approved-reference raw seed 53 was rejected for missing leading margin although its 5.992 s core fit a 6.394 s window. A bounded local onset delay now protects the lead without moving the next anchor. `protected-lead-replay/evidence.json` uses identical waveform/text: rejected before, placed after with 20.25 ms local delay. The final job retains **“Coming, I hope it hasn't seen me. I have three bullets, so ideally I shouldn't fight any of these.”** at tempo 1.0, ending 11:25.748; no compact rewrite is needed. The candidate ledger records the same raw key rejected then accepted. |
| 11:44.674–11:48.818 | Gap ASR and a context hearing support the first `Intentar...`; the context word has broad timing and must not fail an exact-midpoint rule. Meaningful timed overlap preserves it. Final source/target retain **“Intentar. Intentar escapar…” → “To try. To try to escape…”**. Hearings are saved under the long job's `transcribe/second_pass/`. |
| 00:38.49–00:43.22 | An already risky raw seed's ending cannot be repaired with a fade. Raw unsettled endpoints are rejected. For identical valid cached seed 4048, full-tail protection moves the rendered end from 43.068 to 43.217 s, retaining soft generated signal. `cached-minute-final/` contains raw, prior and same-take processed WAVs. |
| 11:19.69–11:25.02, older-reference control | Identical old raw seed 106 ends at 684.566 s under the original processing and 684.883 s with full-tail protection. Signal after a quiet closure is retained, and fades stay outside protected samples. `cached-long-600-790-final/cue_064/`. This establishes preserved generated signal, not recognition of a particular final phoneme. |
| Compact-repair path | A fit rewrite could change `it hasn't seen me` to `I'm not seen` while inheriting the initial translation's verdict. Current repaired text now needs its own bounded bilingual review, with text-bound saved requests/verdicts and neighboring context. Disputed/unconfirmed wording is withheld. The regression exercises semantic restoration and unchanged resume; the final selected longer-passage line uses the full original wording. |

Source-supported pause matching can resolve only a global pathological-pause
rejection. It cannot excuse missing words, wrong numbers, wrong voice features,
or an unsettled ending. Candidate ranking considers source duration and pauses;
it does not always choose the longest take. In the minute's last cue the new end
is **53.565 s**, earlier than the prior **53.786 s**, while the Spanish cue ends
56.435 s. Its two Hardcore decisions remain translated. That remaining timing
difference is not fixed by these changes and must be judged in context.

## Exact cue accounting

Counts describe the kept cues; the thinking event is embedded in minute cue 2.
Uncertain energy gaps are separate from these counts.

| Source passage | Retained / translated / placed / withheld |
| --- | --- |
| 00:00–01:00 | 7 / 7 / 7 / 0 |
| 10:00–13:10 | 24 / 24 / 21 / 3 |
| 14:02–14:12 | 4 / 4 / 3 / 1 |
| 32:06–32:16 | 2 / 2 / 1 / 1 |
| 42:20–42:34 | 2 / 2 / 2 / 0 |
| 44:08–44:16 | 2 / 2 / 1 / 1 |
| 01:14–01:18 | 1 / 1 / 0 / 1 |
| 15:48–15:52 | 1 / 1 / 0 / 1 |
| 36:20–36:26 | 1 / 1 / 0 / 1 |
| **Total** | **44 / 44 / 35 / 9** |

### Unresolved or intentionally unvoiced

- **00:21.866–00:22.436 and 00:44.399–00:45.204:** uncertain `Y...`
  readings remain unvoiced; neighboring text several seconds away cannot close a
  timed gap. The alternative `digamos` reading is not treated as confirmed speech
  or automatically inserted as “I mean.”
- **10:54.695–10:55.243:** cropped gap hearing gives `e`, probability 0.343.
  The original full-job ASR had `Eh`, which survives the cached control; the fresh
  run cannot confidently establish this event and leaves it unresolved. It is a
  possible remaining lost hesitation, not proven keyboard noise or silence.
- **13:00.360–13:00.827:** low-confidence `¡Gracias!` remains unresolved.
- **42:33.408–42:33.723:** a trial recovered `¡Gracias!` from a 20-ms word
  timestamp with probability 0.65 and added “Thanks.” The context hearing does
  not corroborate it. Final English excludes that trial addition, keeps both
  **“Where did it fall?”** questions, and retains the subsequent decision not to
  fight the woman. This rejection does not establish what the acoustic tail was.
- **11:32.245–11:36.117, 11:59.852–12:01.588, 12:53.079–12:54.052:**
  the three long-passage kept lines (`Sí, por acá…`, `y no hay nada…lutear`,
  `Ok, c'est complicado`) remain disputed and withheld. They are retained in
  source/target reports. Conservative review can withhold genuinely clear speech;
  these require source listening rather than a claim of improved continuity.
- **14:06.253–14:07.042:** `No me quiere escribir` versus `Voy a querer
  escribir` is not guessed from game context. No invented “typewriter” is voiced.
- **44:08.002–44:08.931:** `No sé qué parte es` versus `qué parte es`
  remains withheld; the cropped boundary contributes uncertainty.
- **32:06.390–32:06.802:** `Ok, ahí es` is unresolved. **32:12.929–32:14.120:**
  disputed `Ya te vi señora` is withheld. The retained **“Chau, tenemos los 5”**
  still voices the count of five.
- **01:15.980–01:16.520 and 15:48.687–15:48.901:** quiet readings
  `¿Qué es eso?` and `Bien`/`Ya` remain unvoiced, rather than turning uncertain
  sound into “What's that?” or “Okay.”
- **36:20.000–36:24.074:** the eggs/enough reading remains disputed and
  unvoiced. Opposite-polarity source readings are explicitly blocked when present;
  agreement of one cropped ASR pair does not resolve the source automatically.
- No laugh, sigh or other nonverbal microphone passthrough was validated or added.
  It stays disabled. No breath/noise/unknown nomination can authorize English words.

`accounting-final.json`, `results.json`, per-job `report/source_uncertainties.json`
and `report/vocal_events.json` retain exact texts, intervals, IDs and reasons.
The kept source-cue spans intentionally withheld total about 14.318 seconds;
this is not an estimate of actual speech duration. Reported energy outside final
kept cues totals about 2.631 seconds across these disjoint passages, also **not**
a measurement of missing words or speech. Shorter faithful English is accounted
separately from omissions.

## Fresh generation versus identical cached takes

- `cached-minute-final`: 7 retained/translated/placed before and after.
- `cached-long-600-790-final`: 25 retained/translated/placed before and after.
- Both controls use identical translations and existing raw pools, re-evaluate
  saved ASR without fresh hearings, and call no translation provider or TTS.
  Same-take WAVs are separate from reselection; each `evidence.json` records seeds,
  scores, timing and rejection reasons. Waveform images share each passage's clock.
- The current minute cache has 94 unique raw waveforms versus 35 in the f82
  baseline: 59 additional waveforms include unused candidates and abandoned
  standalone-filler trials. Four of the seven final selected takes differ from
  that baseline pool. The main minute comparison therefore includes fresh
  translation/synthesis, not just processing changes.
- Longer fresh jobs use the approved relaxed reference; the old longer baseline
  and its cached control use the older reference. Their voice difference is a
  confound. The longer 3:10 experimental cache contains 229 new waveforms including
  unused text variants; all 21 final selected takes use the approved reference.
  Within that experiment the protected-lead proof isolates identical raw seed 53.
- Synthesis counters describe the last rebuilt schedule. An unchanged resume
  retains those counters; it does not imply another generation call.
- The final reaction-timing safeguard changed none of the nine voices' PCM and
  added no raw takes, provider artifacts or source-ASR files. Regenerated FLOAT
  WAV headers have a new `PEAK` creation timestamp; matching the original file
  hashes after changing only that four-byte timestamp in memory proves the
  samples stayed identical. No audio file was edited for this proof.
  `reaction-safeguard-proof.json` records every passage.

## Technical verification and practical limits

The suite has **137 tests: 136 passed, one existing unavailable recorded fixture
skipped** (`final-tests.log`). Focused regressions cover suffix preservation,
post-filter coverage, timed/uncertain events, prefix verification and caches,
source-supported pauses, bounded retries, raw/processed tails, local leading
room, reaction anchors in both collectors, polarity, text-bound repair reviews
and copied-picture origin.

All 35 placed takes pass protected-signal, settled-endpoint and maximum-tempo
checks. Required media checks pass; unresolved-source checks deliberately fail.
PCM mixes equal the unchanged continuous game bed plus actual placed voice, with
zero measured error. Copied comparison video packets and first displayed source
frames match. No game ducking, video stretching or cumulative anchor shift is used.
Voice identity and calm delivery remain listening judgments; matching reference
hashes and F0/spectral checks cannot establish their perceptual quality.

The longer original recording is missing. This run cannot re-extract its tracks,
listen to establish original track roles, revalidate original-to-extraction
alignment, or compare the missing original's video bytes. It assesses saved mic,
game, raw takes and copied picture. Initial Matroska fixtures normalized seek
preroll; **their pipeline exports are not absolute picture-alignment proof**.
Delivered comparison MP4s copy directly from the full saved picture and verify the
displayed origin. Future preparation aligns all tracks to a verified keyframe;
the real-source smoke check is in `diagnostics/fixture-origin-smoke/`.

The original 20 recorded metadata hashes still match. All nine experimental
reference/Qwen/schedule blocks equal the approved configuration. Reference hashes:

- WAV: `befb8b63e7bbaff92da9a6910cbce3fa147c9328503d9f6b5693274c556333bf`
- Transcript bytes: `f4829900c55d8c142153c3401c82036e89af388a959844f969568a2a9e829c3a`
- Stripped transcript: `5961c35971055464ee01d61014b80501595720a3f63f34b24de436c14e07be88`

Evidence is in `preservation-final.json`. No reference/generation setting was
changed, and no package or model was installed. Existing interpreters were used
under the user's explicit authorization.

Unchanged-resume evidence is in `resume-proofs-final.json` and its two CLI logs.
It compares all cache, handoff, output, schedule and transcription artifacts;
matching resumes perform no generation/provider work and leave those files intact.

There is no new 1–2-hour soak test. This representative set is the minimum before
another full recording: intro hesitation/connected thoughts; combat reactions and
ending; duplicate suffix; repeated question; count/placement; two quiet negatives;
and source polarity/context ambiguity. Keep this set fixed for listening comparisons
and add any newly found failure before authorizing a long run. Score source-event
recall and false additions, meaning/hedges/repetitions, reaction onset error,
internal pause function, complete endings and calm voice separately. Use paired,
level-matched randomized listening and inspect raw/processed WAVs for every ending
complaint; do not rank versions by silence alone.

On the local 24-GB GPU / 32-GB RAM machine, these bounded jobs ran with the existing
models. Full-length work still risks ASR misses, uncertain event nominations,
over-conservative withholding, slow CPU fallback, provider interruption, GPU
contention and bounded retry exhaustion. Checkpoints and exact request/take caches
support restart; no locks/caches need deleting. Confirmed annotated hesitation
recovery is not a general automatic filler/laughter detector. Broader unattended
recall needs validated acoustic event classification and independent source
recognition; it cannot safely be obtained by lowering energy thresholds.

## Reproduce and resume

From the repository root, reuse the isolated minute's configuration snapshot:

```sh
PYTHONDONTWRITEBYTECODE=1 bin/aidub --config config/performance-eval.local.json \
  resume minute-tranquila-corregida-20261014
```

Exit **3 / partial** is expected until source uncertainties are resolved. It is not
permission to accept them silently. The prepared-passage `passage.json` receipts
and ignored local configurations preserve complete source paths and commands.
Use `scripts/performance-evaluate.py run-set` with the configured existing Python
to repeat all receipts; `render`, `excerpts` and `summarize` recreate comparisons
without providers/TTS. Use `bin/aidub auto` for configured provider/repair review.
All work and artifacts remain on the isolated branch/worktree for listening review.
