#!/usr/bin/env python3
"""Persistent, bounded systemd-user supervisor for one aidub auto job."""
from __future__ import annotations

import argparse
import fcntl
import json
import queue
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INTERVAL = 12 * 60
RETRY_DELAYS = (10, 30)
PERMANENT_MARKERS = (
    "authentication", "unauthorized", "forbidden", "quota", "billing",
    "invalid configuration", "invalid config", "provider response", "schema",
    "video not found", "no such file", "not enough space", "insufficient disk", "no space left",
    "disk full", "audio starts before video", "different source video",
)
RECOVERABLE_MARKERS = (
    "out of memory", "cuda error", "worker exited", "worker failed",
    "connection reset", "temporary failure", "timed out", "timeout",
    "connection aborted", "broken pipe",
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def provider_calls(job_dir: Path) -> list[dict]:
    calls = []
    for path in (job_dir / "handoff/batches").glob("*/*/batch_*/response_attempts/*/state.json"):
        state = read_json(path, {}) or {}
        if state.get("status") != "invoking":
            continue
        attempt = next((x for x in reversed(state.get("attempts", [])) if x.get("status") == "invoking"), {})
        started = attempt.get("started_at")
        calls.append({"role": state.get("role"), "started_at_epoch": started,
                      "elapsed_seconds": round(max(0, time.time() - started), 1) if started else None,
                      "state_file": str(path)})
    return calls


def resolve_jobs_dir(config: Path) -> Path:
    cfg = read_json(config)
    if not isinstance(cfg, dict):
        raise RuntimeError(f"Cannot read JSON config: {config}")
    value = Path(cfg.get("jobs_dir", "jobs")).expanduser()
    return (ROOT / value).resolve() if not value.is_absolute() else value.resolve()


def artifacts_signature(job_dir: Path, manifest: dict) -> dict:
    """A compact view of persisted work; file presence/size and provider counters."""
    stages = {k: v.get("status") for k, v in (manifest.get("stages") or {}).items()}
    files = {}
    for rel in ("transcribe", "cache/synth", "cache/quality", "schedule", "mix", "export", "handoff/batches"):
        base = job_dir / rel
        if not base.exists():
            files[rel] = {"files": 0, "bytes": 0}
            continue
        n = size = 0
        latest = 0.0
        for p in base.rglob("*"):
            if p.is_file():
                try:
                    n += 1
                    st = p.stat()
                    size += st.st_size
                    latest = max(latest, st.st_mtime)
                except OSError:
                    pass
        files[rel] = {"files": n, "bytes": size, "latest_mtime": latest or None}
    provider = {"attempts_started": 0, "uncertain_outcomes": 0, "response_reuses": 0,
                "batches_with_responses": 0}
    try:
        from aidub.metrics import provider_metrics
        provider = provider_metrics(job_dir)
    except Exception:
        pass
    provider_states = {}
    for path in (job_dir / "handoff/batches").glob("*/*/batch_*/response_attempts/*/state.json"):
        state = read_json(path, {}) or {}
        key = str(state.get("status", "unknown"))
        provider_states[key] = provider_states.get(key, 0) + 1
    provider["state_counts"] = provider_states
    return {"state": manifest.get("state"), "stages": stages, "files": files, "providers": provider}


def monitor_snapshot(job_dir: Path, config: Path, report: Path, last: dict | None,
                     stage_since: dict, started: float, event_path: Path) -> dict:
    manifest = read_json(job_dir / "manifest.json", {}) or {}
    signature = artifacts_signature(job_dir, manifest) if manifest else {"state": "job_not_created"}
    current_stages = signature.get("stages", {})
    stamp = now()
    for name, status in current_stages.items():
        old = (last or {}).get("stages", {}).get(name)
        if status != old:
            if old is not None:
                append_jsonl(event_path, {"time": stamp, "event": "stage_status_changed", "stage": name,
                                          "from": old, "to": status,
                                          "previous_stage_seconds": round(time.monotonic() - stage_since.get(name, time.monotonic()), 1)})
            stage_since[name] = time.monotonic()
    current_stage = next((name for name, status in current_stages.items() if status == "running"), None)
    if current_stage is None and signature.get("state") == "running":
        current_stage = next((name for name, status in current_stages.items() if status != "complete"), None)
    prior_current = (last or {}).get("current_stage")
    if current_stage != prior_current:
        stage_since["__current__"] = time.monotonic()
        if current_stage:
            append_jsonl(event_path, {"time": stamp, "event": "stage_observed_active", "stage": current_stage,
                                      "note": "Observed from persisted stage state; start may predate this observation."})
    old_provider = ((last or {}).get("providers") or {}).get("state_counts", {})
    new_provider = (signature.get("providers") or {}).get("state_counts", {})
    if new_provider != old_provider:
        append_jsonl(event_path, {"time": stamp, "event": "provider_wait_or_response_state_changed",
                                  "from": old_provider, "to": new_provider,
                                  "note": "Provider state is sampled from persisted batch checkpoints; unchanged counts do not prove a hang."})
    try:
        disk_path = job_dir
        while not disk_path.exists() and disk_path != disk_path.parent:
            disk_path = disk_path.parent
        free = shutil.disk_usage(disk_path).free
        disk = {"free_bytes": free}
    except OSError as e:
        disk = {"error": str(e)}
    in_flight = provider_calls(job_dir)
    snapshot = {"time": stamp, "pid_alive": None, "job_state": signature.get("state"),
                "current_stage": current_stage,
                "current_stage_observed_seconds": (round(time.monotonic() - stage_since["__current__"], 1)
                                                    if current_stage and "__current__" in stage_since else None),
                "provider_calls_in_flight": in_flight,
                "progress": signature, "disk": disk, "service_elapsed_seconds": round(time.monotonic() - started, 1)}
    append_jsonl(event_path, {"time": stamp, "event": "monitor", **snapshot})
    report_data = read_json(report, {}) or {}
    try:
        first = datetime.fromisoformat(report_data["started_at"])
        total = max(0, (datetime.now(timezone.utc) - first.astimezone(timezone.utc)).total_seconds())
    except (KeyError, TypeError, ValueError):
        total = None
    snapshot["total_elapsed_seconds_including_pauses"] = round(total, 1) if total is not None else None
    report_data.update({"last_monitor": snapshot})
    report.write_text(json.dumps(report_data, indent=2) + "\n", encoding="utf-8")
    return signature


def failure_class(exit_code: int, manifest: dict | None, log_tail: str) -> tuple[str, str]:
    error = " ".join(str(x) for x in (
        (manifest or {}).get("error"), (manifest or {}).get("provider_error", {}).get("message"), log_tail[-6000:]
    ) if x).lower()
    state = (manifest or {}).get("state")
    if state == "partial" or exit_code == 3:
        return "partial_terminal", "The pipeline reported partial completion; unresolved source content or failed gates need review."
    if exit_code == 0 and state == "complete":
        return "complete", "Technical pipeline status is complete."
    if state in {"awaiting_translation", "awaiting_repair"} or (manifest or {}).get("provider_error"):
        return "provider_handoff", "Provider handoff failed or awaits work. Inspect identity-bound responses, uncertainty and remaining configured attempts before manual resume."
    if any(term in error for term in PERMANENT_MARKERS):
        return "permanent_blocker", (manifest or {}).get("error") or "A persistent configuration, source, storage, authentication, quota or response blocker was detected."
    if exit_code < 0 or exit_code in {124, 137, 139, 143}:
        return "recoverable_worker", f"Worker process terminated unexpectedly (exit {exit_code}); completed checkpoints remain reusable."
    if any(term in error for term in RECOVERABLE_MARKERS):
        return "recoverable_worker", (manifest or {}).get("error") or "A worker or transient system failure was detected."
    return "unclassified", (manifest or {}).get("error") or f"Supervisor child exited with status {exit_code}; inspect logs and job report."


def apply_provider_fallback(launch: dict, job_dir: Path, launch_path: Path,
                            report_path: Path, event_path: Path) -> tuple[bool, str]:
    """One-way migration of provider specs after a Cursor handoff blocker.

    Only the saved job snapshot's provider mapping changes. All pipeline and
    generation settings, provider state files, and accepted responses stay put.
    """
    fallback_path = launch.get("fallback_config")
    if not fallback_path or launch.get("provider_fallback_applied_at"):
        return False, "No unused fallback config is available."
    from aidub.providers import resolve_role, require_provider, validate_provider_config

    current_path = job_dir / "config.json"
    current = read_json(current_path)
    fallback = read_json(Path(fallback_path))
    if not isinstance(current, dict) or not isinstance(fallback, dict):
        return False, "Cannot read the saved job or fallback configuration."
    current_providers = current.get("providers") or {}
    target_providers = fallback.get("providers") or {}
    if not target_providers:
        return False, "Fallback configuration has no provider mapping."
    for role in ("context", "translation", "review", "back_translation", "repair"):
        spec = resolve_role(target_providers, role)
        validate_provider_config(require_provider(spec, role))
        if spec.get("kind") != "command" or "provider_codex.py" not in " ".join(map(str, spec.get("command", []))):
            return False, f"Fallback role {role} is not configured for the confined Codex adapter."
    old_ids = {r: (resolve_role(current_providers, r) or {}).get("command", [])
               for r in ("context", "translation", "review", "back_translation", "repair")}
    new_ids = {r: (resolve_role(target_providers, r) or {}).get("command", [])
               for r in ("context", "translation", "review", "back_translation", "repair")}
    # Write only the provider mapping, atomically; config snapshot is authoritative.
    current["providers"] = target_providers
    temporary = current_path.with_suffix(".json.fallback-tmp")
    temporary.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, current_path)
    stamp = now()
    launch["provider_fallback_applied_at"] = stamp
    launch["provider_transition"] = {"time": stamp,
                                      "from": "Cursor adapter; model inherited from Cursor selection (Grok 4.7 500K Extra High Fast)",
                                      "to": "gpt-6-luna (ChatGPT/Codex login), reasoning=medium",
                                      "uncertain_cursor_calls_preserved": True}
    launch_path.write_text(json.dumps(launch, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = read_json(report_path, {}) or {}
    transitions = report.setdefault("provider_transitions", [])
    transitions.append({**launch["provider_transition"], "old_provider_commands": old_ids,
                        "new_provider_commands": new_ids,
                        "note": "Existing response/state identities and all non-provider config preserved."})
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    append_jsonl(event_path, {"time": stamp, "event": "provider_fallback_applied",
                              **launch["provider_transition"], "old_provider_commands": old_ids,
                              "new_provider_commands": new_ids})
    return True, "Provider mapping migrated to gpt-6-luna; saved work and request histories retained."


def tail(path: Path, limit: int = 8000) -> str:
    try:
        with path.open("rb") as f:
            f.seek(max(0, path.stat().st_size - limit))
            return f.read().decode("utf-8", "replace")
    except OSError:
        return ""


def run_supervisor(args, *, worker_prefix=None, inhibitor_prefix=None, monitor_interval=DEFAULT_INTERVAL):
    config = Path(args.config).expanduser().resolve()
    job_dir = resolve_jobs_dir(config) / args.name
    logs = ROOT / "runs" / "overnight" / args.name
    logs.mkdir(parents=True, exist_ok=True)
    report_path = logs / "operational-report.json"
    events = logs / "events.jsonl"
    console = logs / "console.log"
    lock_path = logs / "SUPERVISOR.lock"
    lock_fd = lock_path.open("a+")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(f"Another overnight supervisor owns {lock_path}", file=sys.stderr)
        lock_fd.close()
        return 75

    if not args.resume and job_dir.exists() and (job_dir / "manifest.json").exists():
        print(f"Job already exists: {job_dir}; use --resume with the saved launch arguments", file=sys.stderr)
        lock_fd.close()
        return 64
    launch_path = logs / "launch.json"
    if args.resume:
        saved = read_json(launch_path)
        if not saved:
            print(f"No saved launch arguments at {launch_path}", file=sys.stderr)
            lock_fd.close()
            return 64
        launch = saved
        args.video, args.config, args.preset = launch["video"], launch["config"], launch.get("preset")
        args.mic, args.game, args.mixed = launch["mic_ordinal"], launch["game_ordinal"], launch["mixed_ordinal"]
        config = Path(args.config)
        job_dir = resolve_jobs_dir(config) / args.name
    else:
        launch = {"video": str(Path(args.video).expanduser().resolve()), "name": args.name,
                  "config": str(config), "preset": args.preset, "mic_ordinal": args.mic,
                  "game_ordinal": args.game, "mixed_ordinal": args.mixed,
                  "max_process_retries": args.max_process_retries,
                  "retry_delays_seconds": list(args.retry_delays_seconds),
                  "monitor_interval_seconds": monitor_interval}
        if getattr(args, "fallback_config", None):
            launch["fallback_config"] = str(Path(args.fallback_config).expanduser().resolve())
        launch_path.write_text(json.dumps(launch, indent=2) + "\n", encoding="utf-8")

    if not Path(launch["video"]).is_file():
        result = blocked(args, logs, report_path, events, f"Source media is unavailable: {launch['video']}")
        lock_fd.close()
        return result
    report = read_json(report_path, {"job": args.name, "launch": launch, "events": []}) or {}
    previous_stop = report.get("stopped_at")
    if args.resume and previous_stop:
        try:
            paused = max(0, (datetime.now(timezone.utc) - datetime.fromisoformat(previous_stop).astimezone(timezone.utc)).total_seconds())
        except (TypeError, ValueError):
            paused = None
        append_jsonl(events, {"time": now(), "event": "manual_resume", "previous_stop": previous_stop,
                              "manual_pause_seconds": round(paused, 1) if paused is not None else None})
    report.update({"job": args.name, "launch": launch, "started_at": report.get("started_at", now()),
                   "status": "running", "manual_interventions": report.get("manual_interventions", [])})
    report.pop("stopped_at", None)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    append_jsonl(events, {"time": now(), "event": "supervisor_started", "resume": args.resume})

    stop = threading.Event()
    child = {"proc": None}
    def handle_signal(signum, _frame):
        stop.set()
        proc = child.get("proc")
        if proc and proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGINT)
            except ProcessLookupError:
                pass
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    start_mono = time.monotonic()
    stage_since = {}
    identical = {}
    retry_index = 0
    final_code = 1
    with console.open("a", encoding="utf-8", buffering=1) as log:
        def say(message):
            line = f"[{now()}] {message}"
            log.write(line + "\n")
            print(line, flush=True)
        while not stop.is_set():
            if not Path(launch["video"]).is_file():
                final_code = blocked(args, logs, report_path, events, f"Source media disappeared: {launch['video']}")
                break
            cmd = worker_prefix or [str(ROOT / "bin/aidub")]
            cmd += ["--config", launch["config"], "auto", launch["video"], "--name", launch["name"]]
            cmd += ["--mic-ordinal", str(launch["mic_ordinal"]), "--game-ordinal", str(launch["game_ordinal"]),
                    "--mixed-ordinal", str(launch["mixed_ordinal"])]
            if launch.get("preset"):
                cmd += ["--preset", launch["preset"]]
            say(f"Starting same job {args.name}; attempt {retry_index + 1}; command arguments are saved in launch.json")
            append_jsonl(events, {"time": now(), "event": "worker_started", "attempt": retry_index + 1})
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            env["AIDUB_INHIBITOR_HELD"] = "1"
            wrapped = (inhibitor_prefix or ["systemd-inhibit", "--what=sleep", "--mode=block", "--who=aidub-overnight",
                       "--why=Overnight dubbing job and recovery waits", "--"]) + cmd
            proc = subprocess.Popen(wrapped, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, bufsize=1, start_new_session=True)
            child["proc"] = proc
            output_queue = queue.Queue()
            def drain_output(stream):
                for output_line in stream:
                    output_queue.put(output_line)
                output_queue.put(None)
            reader = threading.Thread(target=drain_output, args=(proc.stdout,), daemon=True)
            reader.start()
            last_monitor = time.monotonic()
            latest = monitor_snapshot(job_dir, config, report_path, None, stage_since, start_mono, events)
            report = read_json(report_path, {}) or {}
            report.setdefault("last_monitor", {})["pid_alive"] = proc.poll() is None
            report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            while proc.poll() is None:
                try:
                    line = output_queue.get(timeout=1)
                except queue.Empty:
                    line = ""
                if line:
                    log.write(line)
                    print(line, end="", flush=True)
                if time.monotonic() - last_monitor >= monitor_interval:
                    latest = monitor_snapshot(job_dir, config, report_path, latest, stage_since, start_mono, events)
                    report = read_json(report_path, {}) or {}
                    report.setdefault("last_monitor", {})["pid_alive"] = proc.poll() is None
                    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
                    say(f"monitor: state={latest.get('state')} progress={json.dumps(latest, sort_keys=True)}")
                    last_monitor = time.monotonic()
                if stop.is_set():
                    try:
                        os.killpg(proc.pid, signal.SIGINT)
                    except ProcessLookupError:
                        pass
                    break
            if stop.is_set() and proc.poll() is None:
                try:
                    proc.wait(timeout=300)
                except subprocess.TimeoutExpired:
                    say("Graceful stop exceeded 300s; waiting for systemd's final kill policy")
            code = proc.wait()
            reader.join(timeout=2)
            while True:
                try:
                    remaining = output_queue.get_nowait()
                except queue.Empty:
                    break
                if remaining:
                    log.write(remaining)
                    print(remaining, end="", flush=True)
            proc.stdout.close()
            child["proc"] = None
            manifest = read_json(job_dir / "manifest.json", {})
            category, reason = failure_class(code, manifest, tail(console))
            if provider_calls(job_dir) and category == "recoverable_worker":
                category = "provider_handoff"
                reason = "The worker ended during an active provider call. Its result may be externally complete but not locally saved; inspect the identity-bound state and uncertainty record before any resume."
            append_jsonl(events, {"time": now(), "event": "worker_exited", "exit_code": code,
                                  "category": category, "job_state": (manifest or {}).get("state")})
            report = read_json(report_path, {}) or {}
            report["last_worker_exit"] = {"time": now(), "exit_code": code, "category": category,
                                          "job_state": (manifest or {}).get("state"), "reason": reason}
            report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            if stop.is_set():
                say("Stopped by request; checkpoints and provider records retained. Resume with the saved launch arguments.")
                report.update(status="manually_paused", stopped_at=now())
                report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
                final_code = 130
                break
            if category in {"complete", "partial_terminal"}:
                final_code = code
                report.update(status=category, finished_at=now())
                report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
                say(reason)
                break
            if category == "provider_handoff":
                changed, transition_message = apply_provider_fallback(launch, job_dir, launch_path,
                                                                     report_path, events)
                if changed:
                    say(transition_message)
                    # Exactly one same-job continuation on Luna; subsequent failures block.
                    launch["provider_fallback_applied_at"] = launch.get("provider_fallback_applied_at") or now()
                    retry_index = 0
                    continue
            if category != "recoverable_worker" or retry_index >= launch["max_process_retries"]:
                final_code = code or 1
                report.update(status="human_intervention_required", finished_at=now(), actionable_reason=reason)
                report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
                say(f"Stopping safely ({category}): {reason}")
                break
            identical[category] = identical.get(category, 0) + 1
            if identical[category] >= 2:
                report.update(status="human_intervention_required", finished_at=now(), actionable_reason=
                              f"Repeated identical failure ({category}): {reason}")
                report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
                say(f"Repeated identical failure; stopping: {reason}")
                final_code = code or 1
                break
            delays = launch["retry_delays_seconds"]
            delay = delays[min(retry_index, len(delays) - 1)]
            retry_index += 1
            append_jsonl(events, {"time": now(), "event": "recovery_wait_started", "category": category,
                                  "delay_seconds": delay, "reason": reason})
            say(f"Recovering after {category}; next same-job resume in {delay}s. Sleep remains inhibited.")
            if stop.wait(delay):
                continue
    if final_code not in (0, 3, 130, 75):
        report = read_json(report_path, {}) or {}
        report.setdefault("status", "human_intervention_required")
        report["final_exit_code"] = final_code
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    append_jsonl(events, {"time": now(), "event": "supervisor_exited", "exit_code": final_code})
    lock_fd.close()
    return final_code


def blocked(args, logs: Path, report_path: Path, events: Path, reason: str) -> int:
    logs.mkdir(parents=True, exist_ok=True)
    row = {"job": args.name, "status": "blocked", "blocked_at": now(), "actionable_reason": reason}
    report_path.write_text(json.dumps(row, indent=2) + "\n", encoding="utf-8")
    append_jsonl(events, {"time": now(), "event": "blocked", "reason": reason})
    print(f"BLOCKED: {reason}\nReport: {report_path}", file=sys.stderr)
    return 75


def start(args):
    if not re_name(args.name):
        raise SystemExit("Invalid job name; use letters, numbers, dot, underscore, hyphen")
    config = Path(args.config).expanduser().resolve()
    saved_launch_path = ROOT / "runs" / "overnight" / args.name / "launch.json"
    saved_launch = read_json(saved_launch_path) if args.resume else None
    if args.resume:
        if not saved_launch:
            raise SystemExit(f"No saved launch arguments at {saved_launch_path}")
        config = Path(saved_launch["config"]).expanduser().resolve()
    if not config.is_file():
        raise SystemExit(f"Config unavailable: {config}")
    logs = ROOT / "runs" / "overnight" / args.name
    logs.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(Path(__file__).resolve()), "run", "--name", args.name,
           "--config", str(config), "--max-process-retries", str(args.max_process_retries),
           "--retry-delays", ",".join(map(str, args.retry_delays_seconds))]
    if args.resume:
        cmd.append("--resume")
    else:
        cmd += ["--video", str(Path(args.video).expanduser().resolve()), "--mic", str(args.mic),
                "--game", str(args.game), "--mixed", str(args.mixed)]
        if args.preset:
            cmd += ["--preset", args.preset]
        if args.fallback_config:
            fallback = Path(args.fallback_config).expanduser().resolve()
            if not fallback.is_file():
                raise SystemExit(f"Fallback config unavailable: {fallback}")
            launch_path = logs / "launch.json"
            saved_launch = read_json(launch_path, {}) or {}
            saved_launch["fallback_config"] = str(fallback)
            launch_path.write_text(json.dumps(saved_launch, indent=2) + "\n", encoding="utf-8")
            cmd += ["--fallback-config", str(fallback)]
    cfg = read_json(config, {}) or {}
    setenv = [f"--setenv=AIDUB_CONFIG={config}"]
    for spec in (cfg.get("providers") or {}).values():
        for key in ("api_key_env", "base_url_env", "model_env"):
            name = spec.get(key)
            value = os.environ.get(name, "") if name else ""
            if name and value:
                setenv.append(f"--setenv={name}={value}")
    unit = f"aidub-overnight-{args.name}"
    subprocess.run(["systemd-run", "--user", "--collect", f"--unit={unit}",
                    "--working-directory", str(ROOT), "--property=KillMode=control-group",
                    "--property=KillSignal=SIGINT", "--property=TimeoutStopSec=300", *setenv,
                    "/usr/bin/systemd-inhibit", "--what=sleep", "--mode=block", "--who=aidub-overnight",
                    "--why=Overnight dubbing job and recovery waits", "--", *cmd], check=True)
    print(f"Unit: {unit}.service\nJob: {args.name}\nLogs/report: {logs}")


def re_name(value: str) -> bool:
    return bool(value) and all(c.isalnum() or c in "._-" for c in value)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="action", required=True)
    s = sub.add_parser("start", help="start a future job as a persistent user service")
    s.add_argument("video", nargs="?")
    s.add_argument("--name", required=True)
    s.add_argument("--config", default=str(ROOT / "config/local.json"))
    s.add_argument("--preset")
    s.add_argument("--mic", type=int, default=2)
    s.add_argument("--game", type=int, default=1)
    s.add_argument("--mixed", type=int, default=0)
    s.add_argument("--max-process-retries", type=int, default=2)
    s.add_argument("--retry-delays", default="10,30", help="increasing seconds, two values; default 10,30")
    s.add_argument("--resume", action="store_true")
    s.add_argument("--fallback-config", help="one-way provider mapping used only after provider_handoff")
    s.set_defaults(func=start)
    r = sub.add_parser("run", help=argparse.SUPPRESS)
    r.add_argument("--name", required=True); r.add_argument("--config", required=True)
    r.add_argument("--video"); r.add_argument("--mic", type=int); r.add_argument("--game", type=int); r.add_argument("--mixed", type=int)
    r.add_argument("--preset"); r.add_argument("--max-process-retries", type=int, default=2)
    r.add_argument("--retry-delays", default="10,30")
    r.add_argument("--resume", action="store_true")
    r.add_argument("--fallback-config")
    r.set_defaults(func=lambda a: run_supervisor(a))
    st = sub.add_parser("status", help="show service and operational report")
    st.add_argument("name"); st.set_defaults(func=status)
    sp = sub.add_parser("stop", help="request graceful interruption of one service")
    sp.add_argument("name"); sp.set_defaults(func=stop)
    args = p.parse_args()
    if args.action == "start" and not args.resume and not args.video:
        p.error("start requires VIDEO unless --resume is used")
    if args.action == "start" and not 0 <= args.max_process_retries <= 2:
        p.error("--max-process-retries must be 0..2")
    if args.action == "start":
        try:
            args.retry_delays_seconds = [int(x) for x in args.retry_delays.split(",")]
        except ValueError:
            p.error("--retry-delays must contain two comma-separated integers")
        if len(args.retry_delays_seconds) != 2 or any(x < 0 or x > 3600 for x in args.retry_delays_seconds) or args.retry_delays_seconds[0] >= args.retry_delays_seconds[1]:
            p.error("--retry-delays must be increasing values from 0 to 3600, for example 10,30")
    if args.action == "run":
        args.retry_delays_seconds = [int(x) for x in args.retry_delays.split(",")]
    return args.func(args)


def status(args):
    unit = f"aidub-overnight-{args.name}.service"
    subprocess.run(["systemctl", "--user", "show", unit, "-p", "ActiveState", "-p", "SubState", "-p", "Result"], check=False)
    path = ROOT / "runs" / "overnight" / args.name / "operational-report.json"
    print(f"Report: {path}")
    data = read_json(path)
    if data:
        print(json.dumps(data, indent=2))
    return 0


def stop(args):
    unit = f"aidub-overnight-{args.name}.service"
    control = subprocess.run(["systemctl", "--user", "show", unit, "--property=ControlGroup", "--value"],
                             text=True, capture_output=True, check=False)
    group = control.stdout.strip()
    if control.returncode or not group:
        print(f"Unit is not active: {unit}")
        return 0
    procs = Path("/sys/fs/cgroup") / group.lstrip("/") / "cgroup.procs"
    try:
        pids = [int(p) for p in procs.read_text().split()]
    except OSError as exc:
        print(f"Cannot inspect {procs}; leaving service untouched: {exc}", file=sys.stderr)
        return 1
    supervisor = None
    for pid in pids:
        try:
            cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace")
        except OSError:
            continue
        if "scripts/overnight.py run" in cmdline:
            supervisor = pid
            break
    if supervisor is None:
        print(f"Could not identify the supervisor process in {unit}; leaving it untouched.", file=sys.stderr)
        return 1
    os.kill(supervisor, signal.SIGINT)
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        active = subprocess.run(["systemctl", "--user", "show", unit, "--property=ActiveState", "--value"],
                                text=True, capture_output=True, check=False)
        if active.returncode or active.stdout.strip() in {"inactive", "failed", ""}:
            return 0
        time.sleep(1)
    print("Graceful stop is still in progress after 300s. The inhibitor remains held; inspect the worker before acting.",
          file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
