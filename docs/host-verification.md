# Host verification still required

Host permissions now allow the NVIDIA driver and user systemd bus. The configured 81-second sample was run, interrupted during synthesis, resumed and exported partial; see [measured results](hardening-verification.md). No representative long source was available. The existing 3234.417-second historical job's source is absent here; its old report does not validate this branch.

The workstation's ignored `config/local.json` preserves the existing environments, reference and command providers. Check the configured track roles by listening before any run. These commands create new jobs and leave historical artifacts intact.

## Short production sample

From a host terminal:

```bash
cd /home/siamarino/ai-dubbing-e2e-unattended
scripts/start-host-verification.sh \
  /home/siamarino/vids-sample/base-video.mp4 hardening-short-20261010 \
  config/local.json 2 1 0
```

The launcher prints a unique unit name. It starts a persistent user service, never replaces another service, records `resources.json` wall time and Linux exited-child peak RSS through a stdlib wrapper, and runs one owned GPU monitor. Peak RSS is a maximum, not the sum of concurrent workers. Monitor VRAM includes other host workloads; do not attribute it all to this job. Pipeline metrics/provider states contain per-stage wall time, process peak RAM, Qwen inference/VRAM metadata, provider attempts/reuse/uncertain outcomes, cue counts, omissions and validation checks. No system `time` package is required.

```bash
bin/aidub status hardening-short-20261010
bin/aidub validate hardening-short-20261010
# Same source/name to verify that valid stages and paid provider batches are reused:
scripts/start-host-verification.sh \
  /home/siamarino/vids-sample/base-video.mp4 hardening-short-20261010 \
  config/local.json 2 1 0
```

Do not launch the second command until the first unit has exited. Job locking will reject a competing runner. Inspect `jobs/hardening-short-20261010/report/`, `handoff/batches/`, `mix/gain.json` and `runs/hardening/host/hardening-short-20261010/`.

The pipeline's partial exit code 3 can appear as a failed systemd unit; consult the job report and resources.json to distinguish an explicit partial export from a crash. Use a new job name for a fresh sample, or the existing name to inspect/cache-resume the measured partial output.

## Long source and interruption/resume

Choose an available original OBS recording of at least an hour. The known October 7 source was about 54 minutes and is absent in this environment. Supply the real path and listened-to ordinals:

```bash
VIDEO='/absolute/path/to/an-hour-or-longer-recording.mkv'
ffprobe -v error -show_entries format=duration -of default=nw=1 "$VIDEO"
df -h /home/siamarino
scripts/start-host-verification.sh "$VIDEO" hardening-long-20261010 config/local.json 2 1 0
```

Watch the exact printed unit and job logs. After completed transcription windows or synthesis/verification checkpoints exist, interrupt **only this verification unit**, ideally outside a provider call:

```bash
systemctl --user kill --kill-whom=all --signal=SIGINT 'THE-EXACT-PRINTED-UNIT.service'
systemctl --user show 'THE-EXACT-PRINTED-UNIT.service' -p ActiveState -p SubState
# When it is inactive/failed, relaunch the same job/source:
scripts/start-host-verification.sh "$VIDEO" hardening-long-20261010 config/local.json 2 1 0
```

Wait for the owned unit to exit before resuming; KillMode covers its children. Do not stop unrelated services. An interruption during a provider call can leave uncertain billing even when local processes are reaped. Confirm matching saved responses are reused and the uncertainty is reported honestly. Remaining bounded attempts can retry; no exactly-once claim is made.

```bash
bin/aidub status hardening-long-20261010
bin/aidub validate hardening-long-20261010
```

Record source duration/dimensions, wall/peak RAM, Qwen peak VRAM and monitor scope, provider attempts/reuses/uncertainty, window/candidate cache hits, kept/placed/unplaced cue counts, reasons, bitstream/decode/timing and game-bed checks. Compare generated English with Spanish and listen to quiet game stretches and reactions. A passed long run validates that recording technically; it is not broad release reliability or listening approval.
