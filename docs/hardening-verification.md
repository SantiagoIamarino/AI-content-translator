# Hardening verification — 2026-10-10

Checks performed during implementation from published snapshot `a0c8628ea4ff60d6deccbd7e551cb39e0399dfd9`. Reports under docs/validation.md and older jobs are historical evidence. Main remains `7e9b8282525fabb4e73342e9b458470bde2b23b0`. No packages/models were installed, and no unrelated service was stopped.

## Automated checks

Using the existing Qwen environment:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. \
  /home/siamarino/ai-dubbing/qwen3-tts/.venv/bin/python \
  -m unittest discover -s tests -v
```

74 tests ran: 73 passed, one skipped because the historical Deepseek/reference waveform fixture is absent. Unittest wall time was 2.867 s; measured process wall time 2.966 s, exited-child peak RSS 65.0 MiB. Python AST parsing, default/example JSON parsing, shell syntax and `git diff --check` passed.

Regression coverage includes:

- A real competing subprocess during fake-provider handoff; the outer job lock remains held and manual run is rejected.
- A provider response saved before acceptance and an uncertain call without a saved response; matching recovery avoids reinvocation, different requests cannot reuse responses, and bounded budgets persist.
- Retry feedback in command and mocked HTTP payloads, independent batch recovery, preflight without spending an attempt, timeout/process-group cleanup, and canonical-response corruption recovery.
- Quality/model/language/waveform changes, legacy migration, and independent source ASR checkpoint identity. Verification changes preserve synthesis identity.
- Worker stderr beyond pipe capacity, startup errors, stdout chatter/flood, request timeout, interrupted shutdown and persisted job errors.
- Missing MKV metadata and N/A timestamps, nonzero video timestamps, B-frame presentation endpoints, unsupported codec/container refusal, real FFmpeg export/decode and copied-video identity.
- Voice-only peak management when the sum exceeds the ceiling, explicit insufficient headroom, block/previous short-fixture placement equivalence, block RMS/convolution equivalence, bounded heap processing and source-window interruption recovery.
- Fake-model/fake-provider full auto including compact repair, one backend load, acceptance and cached resume. This regression does not validate real voice quality.

## Configured short sample and interruption/resume

Original source: `/home/siamarino/vids-sample/base-video.mp4`, 81.716667 s, 1920×1080, 60 fps, 4903 frames. Existing listened-to sample ordinals: mixed 0, game 1, mic 2. This is not a 1440p60 or long-recording test.

Used ignored `config/local.json`, the existing Cursor command provider, local Whisper Turbo weights and Qwen 1.7B English ICL/reference B. No provider was substituted. A persistent user systemd service ran job `hardening-short-20261010`.

| Measurement | Observed result |
| --- | --- |
| First invocation, interrupted during synthesis | 160.169 s; exit 130; exited-child peak RSS 4,940,247,040 bytes |
| Resume to export/validation | 43.761 s; exit 3 (partial); exited-child peak RSS 4,948,176,896 bytes |
| Later cached resume | 1.338 s; exit 3; peak RSS 42,336,256 bytes; all stages unchanged |
| Source transcription | One worker/window; 9.395 s including startup/request |
| Provider attempts | One translation attempt; zero repair attempts or uncertain outcomes; no repeated call on either resume |
| Checkpoints before interruption | 18 synthesis WAVs and 18 quality results; all 54 WAV/metadata/quality files retained with identical hashes |
| Work reused on synthesis resume | 18 synthesis cache hits and 18 quality cache hits; 15 new candidates/checks |
| Total candidate WAVs | 33; one Qwen backend/prompt load per synthesis process, two processes because of the deliberate interruption |
| Qwen process peak GPU allocation | Maximum candidate metadata 4.643 GiB; backend load metadata 3.915 GiB |
| Whole-host GPU monitor peak | 11,387 MiB; includes generated ASR and unrelated host usage, not a per-job allocation measurement |
| Kept / placed / unplaced | 26 / 26 / 0; three chosen fit alternates; zero compact revisions |
| Dropped ASR rows | Three near-silence rows and one empty row; recorded with text/timing/reason |
| Untranscribed energy | Six spans, about 0.868 s total; their meaning requires listening |
| Final status | **partial** because `source_energy_accounted` failed; output `english_PARTIAL.mp4` |

The short output passes source integrity, both output decodes, source/output frame counts, duration, geometry/codec, copied-video MD5 `a6b33fc58ce52e27caedf6948228cd47`, continuous game-bed relation (maximum error 0), placement/quality/transcription/voice-edge checks and protected-file checks. Game gain stays 1; no new PCM clipping. Decoded English AAC peak is 0.31458 with zero full-scale samples. The six energy gaps prevent a complete claim even though every kept cue was placed.

The units exited before another invocation was launched. The deliberate interruption exposed shutdown/error-persistence weaknesses; cleanup and error setters were fixed and covered by regressions before the later cached resume. The original interrupted process's log remains evidence of the failure, rather than being rewritten.

Local artifacts are intentionally ignored/unpublished:

- `jobs/hardening-short-20261010/report/validation.json` and `.md`, stage metrics, synthesis and quality caches.
- `runs/hardening/host/hardening-short-20261010/20261010T191220Z/`, `20261010T191535Z/`, `20261010T191656Z/`: pipeline/resource logs, resource JSON and host GPU samples.
- `runs/hardening/host/hardening-short-20261010/pre-interruption.json`: hashes captured before interrupting.

## Synthetic one-hour audio benchmark

Reproduce in a **new** output directory (the script refuses to overwrite one):

```bash
PYTHONPATH=. /path/to/qwen-env/bin/python scripts/benchmark-block-audio.py \
  runs/hardening/a-new-hour-benchmark --seconds 3600
```

This generated 172,800,000 stereo frames at 48 kHz, three voice cues, and an indexed energy map. It is synthetic audio only: no gameplay picture, language providers, real ASR/Qwen inference or listening assessment.

| Measurement | Result |
| --- | --- |
| Block size / process peak RSS | 65,536 frames / 40,951,808 bytes (39.1 MiB) |
| Generate / mix / validate / index | 3.372 / 2.488 / 1.670 / 3.587 s |
| Total wall / stored bytes | 11.118 s / 2,764,859,172 bytes |
| Unadjusted sum / resulting peak | 1.400018 / 0.990000 (float rounding) |
| Cue voice gain / game gain | 0.316636 / 1.0 |
| Game-bed comparison error / new clipping | 0 / 0 |
| Placed cues | 3 of 3 |

Results remain in ignored `runs/hardening/bench-hour-20261010/benchmark.json`. File-system cache and fast storage affect throughput. Peak RSS measures this process, not aggregate GPU/model workers. Controlled short fixtures independently compare block output with the prior placement/convolution behavior.

## Remaining verification

No available representative source of at least an hour was found in the supplied recordings directories. The known historical 54-minute October 7 source is absent. **No long real-model run or long interruption/resume passed.** Use docs/host-verification.md once a source is available; do not duplicate workers or stop unrelated services.

No listening approval was performed, including for the six short-sample energy gaps. Real compact repair was unnecessary for this sample and remains supported by fake-model/provider tests. Fresh-clone installation, other GPUs/drivers and another person's voice/model configuration remain unverified. Top-level pins are observed constraints, not a complete dependency lock. The branch is ready for code review and further host validation, not designation as a proven 1–2 hour release.
