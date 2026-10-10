# Unattended execution

`bin/aidub auto VIDEO --name NAME --mic-ordinal N --game-ordinal N --mixed-ordinal N` creates or resumes one job. Existing job snapshots are authoritative. A different source path under the same name is rejected. Both translation and repair providers must be explicit and available.

The outer job lock remains held during provider calls and acceptance. `run_job` receives that already-held lock; it does not acquire a nested lock for the same path. Batch response locks protect standalone provider entry points too, always after the outer job lock. Both lock types are nonblocking and OS-owned. Persistent LOCK files are harmless after exit.

Provider batches keep stable cue IDs and expose neighbors only as read-only context. `batching.max_cues` and `max_chars` bound complete serialized request size. An individual cue plus context exceeding the limit is a diagnostic, not an omission. Full response aggregation/acceptance happens only after all batches validate; accepted batches stay durable across interruption.

Each identity directory records `state.json`, immutable attempt requests/responses, and stdout/stderr logs. Request identity includes the role, original request, provider endpoint/model/command and repair's current English. Timeout/attempt limits do not change response identity. Editing the source text, provider or relevant request context invalidates only mismatched batches. Changing batch limits may change boundaries and thus request identities.

A response saved before acceptance is reused after schema validation. A timeout or interrupted call without a durable response is recorded as an uncertain external completion/billing outcome. Local command process groups are reaped on timeout/interruption. External requests cannot be made exactly-once across that boundary. Remaining bounded attempts may retry; exhaustion stays resumable with a recorded error. To authorize a further attempt, stop the job, fix the issue and raise `max_attempts` up to 5. No provider is silently substituted.

Schema retry errors are included in the next request's `validation_feedback`, including command and OpenAI-compatible providers. The old `.retry.txt` mechanism is no longer used. `timeout_sec` and `max_response_bytes` bound provider execution and response parsing. Credentials come from configured environment variables and remain outside tracked config.

Qwen/prompt reuse, synthesis cache keys, manual handoffs, bounded quality/fit seeds, leading-silence placement, and explicit partial exports remain. Source ASR uses one worker across checkpointed overlapping windows; generated-speech ASR uses one worker within each schedule pass. Diagnostics are file-backed and stdout is JSON only. See README for setup, headroom policy, heuristic limits and technical gates.
