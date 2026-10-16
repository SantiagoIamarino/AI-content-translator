# Overnight jobs

`bin/aidub auto` remains the pipeline runner. `scripts/overnight.py` starts one
supervised invocation as a transient systemd **user** service and reuses that
job identity on bounded recovery. It does not install a unit, enable a boot
service, change translation or synthesis settings, or resume any job on its own.

## Start a future recording

From this checkout, after confirming the recording path and listening to the
audio streams to identify the microphone, game and mixed ordinals:

```bash
python3 scripts/overnight.py start /absolute/path/new-recording.mkv \
  --name new-recording-en \
  --config config/overnight-performance-tranquila.local.json \
  --preset performance \
  --mic N --game N --mixed N
```

Replace the path/name and set each ordinal after listening to that recording's
streams. The dedicated ignored local config keeps the evaluated `performance`
settings and approved tranquil reference, while omitting the one-minute source
and its microphone-bound annotations. The default preset is omitted only for
the fixed-generation default pipeline. The config, preset and ordinals are
saved in `runs/overnight/NAME/launch.json`; resume always uses those saved
arguments. An existing job cannot be silently replaced by `start`. Pipeline
config snapshots remain authoritative after job creation.

## Follow and control

```bash
python3 scripts/overnight.py status recording-en-20261020
journalctl --user -fu aidub-overnight-recording-en-20261020.service
tail -F runs/overnight/recording-en-20261020/console.log
python3 scripts/overnight.py stop recording-en-20261020
systemctl --user show aidub-overnight-recording-en-20261020.service \
  -p ActiveState -p SubState -p Result
python3 scripts/overnight.py start --resume --name recording-en-20261020
```

Wait until the service is inactive before resuming. The stop command interrupts
the supervisor, which forwards SIGINT to the worker process group and allows up
to five minutes for graceful shutdown. The inhibitor stays held until that
shutdown finishes. The pipeline retains its completed windows, takes, provider records
and other checkpoints. Never remove `LOCK` or the supervisor lock to force a
second runner. `aidub status NAME` and `aidub validate NAME` remain available.

Durable stdout/stderr are appended to `runs/overnight/NAME/console.log` and are
also sent to the service journal. `operational-report.json` is the current
summary; `events.jsonl` records worker starts/exits, recovery waits, sampled
pipeline stages, in-flight provider calls and checkpoint-state changes, manual
stops/resumes and pauses, blocker reports and supervisor exit codes. The report
distinguishes current service time from total wall time including manual
pauses. Pipeline `report/stage_metrics.jsonl`,
provider attempt states and validation reports remain the authoritative detailed
measurements. The monitor samples every 12 minutes by default and records
elapsed wall time, stage state/duration, checkpoint file counts/bytes/mtime,
provider response/uncertainty counters and in-flight call durations, service
process health and free disk.
Stage duration is the time since the monitor first observed that stage after a
change; the full stage start can predate that observation. Sampling gaps,
including a service-manager outage, are not interpolated; their durations
remain unknown.

## Recovery limits

The pipeline's own timeouts, provider `max_attempts` and handoff-round limits
remain authoritative and persisted in the job/config and identity-bound batch
state. A supervisor restart cannot reset them. Saved responses are reused by
the pipeline. An uncertain provider call without a durable response is not
retried by this supervisor: review its batch state, uncertainty note and
remaining configured provider budget before a manual resume. Authentication,
quota, invalid response/configuration, unavailable source, and disk blockers
stop for human action. A missing mounted Windows source is reported as blocked;
the supervisor does not loop while it is absent.

For process-level worker crashes or recognized transient worker failures, the
supervisor permits up to two same-job retries, after 10 then 30 seconds. The
limits and increasing waits are configurable at launch:

```bash
python3 scripts/overnight.py start VIDEO --name NAME --config CONFIG \
  --max-process-retries 1 --retry-delays 10,30
```

Retries stop earlier after the same failure class repeats. A retry reruns
`aidub auto` against the same job so the job lock is reacquired normally and
valid stage/provider checkpoints are reused. There is no automatic retry after
exit code 3 (partial), provider handoff failure/exhaustion, unknown failure or
failed required gate. Partial output is technical partial status, not voice or
listening approval; unresolved or unplaced source content requires review.
The pipeline uses exit 0 for complete, 3 for partial, 2 for an explicit
translation/repair handoff from `run`, and 1 for failure. Overnight `auto`
handles handoffs internally; an exhausted/failed provider handoff is recorded
in the job and operational report and needs inspection. Systemd may label the
unit failed for the intentional partial exit 3, so check `aidub status NAME`,
the validation report and the operational report before treating that unit
result as a crash.

The monitor never kills a live worker for quiet logs or an unchanged checkpoint.
The long Whisper request and media timeouts, GPU inference, validation and
provider calls can all be quiet while healthy. It reports progress and disk
space; a human decides whether a live worker is blocked after examining its
stage-specific log, child processes and persisted evidence. A graceful stop is
used before any manual restart.

## Logout, sleep and reboot

The user systemd manager and user bus are available on this workstation; there
are currently no aidub user units. `Linger=no`, so a transient user service
survives closing its launching terminal and the end of this agent session while
the user manager remains active, but it is not guaranteed to survive a full
logout. Lingering was not enabled. The persistent `systemd-inhibit --what=sleep`
process covers the worker and recovery waits, so system suspend is blocked while
the service is active; screen blanking/locking is unaffected.

A reboot terminates the transient service. No boot unit or automatic job
resumption is enabled, so an old or paused job cannot start unexpectedly after
boot. After login, confirm the recording mount is present and inspect the report,
then resume explicitly with the saved launch arguments. If the source mount is
missing, the report says `blocked`; restore the mount before explicit resume.

## Verification

Run the harmless fake-worker checks with:

```bash
python3 scripts/test_overnight.py
```

They exercise success, transient recovery, permanent failure, retry exhaustion,
interruption/checkpoint reuse, duplicate supervisors, slow healthy work,
inhibitor lifetime/release and terminal partial status. They do not call a
translation or synthesis provider, load a model, or touch an existing job.
