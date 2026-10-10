# Remaining validation and development

The unattended snapshot now has provider batching/recovery, bounded audio processing, independent synthesis/quality caching and explicit partial policies. See README and hardening-verification.md for current behavior and measured evidence; docs/validation.md describes older runs.

Before calling this a reliable long-video release:

1. Supply an original recording of at least an hour, listen to its audio track roles, and run the persistent host procedure with interruption/resume.
2. Review the short sample's six untranscribed-energy spans and four dropped ASR rows. Review long-recording omissions, reactions, names, clicks, timing and voice drift by listening.
3. Verify fresh-clone provisioning on a second machine. Top-level environment pins do not freeze all dependencies or establish driver compatibility on other machines.
4. Review real compact-repair behavior. Fake-provider/model regressions exercise it; the real short run required no repair request.

For the quality preset (docs/quality.md, runs/quality/REPORT.md): listen to the short-sample comparison excerpts; run it on a long recording; provision large-v3 only if wanted and compare it with `asr-compare` before switching; consider letting reviewer-disputed source lines trigger a second ASR hearing; revisit the 0.6 loudness-gain floor that clips quiet cues; add an optional, calibrated speaker-embedding signal (never a hard gate for short cross-language phrases); laughter/scream passthrough remains deferred.

Optional future work includes stronger speaker embeddings, better text alignment and speech verification, and reviewed speech recovery for energy gaps. The configurable harmonic and pitch/brightness heuristics remain heuristics. These improvements do not require an agent framework or replacing the working CLI.
