"""One-command driver: init, run, provider handoffs, resume, validate."""

from __future__ import annotations

import time
from pathlib import Path

from .config import require_schedule_defaults
from .job import Job
from .pipeline import (
    accept_repair,
    accept_translation,
    export_repair,
    export_translation,
    job_path,
    run_job,
)
from .providers import ProviderError, invoke_checked, require_provider
from .util import read_json, write_json


def _ordinals(cfg: dict, mic, game, mixed) -> None:
    if mic is not None:
        cfg["audio_mapping"]["mic_ordinal"] = mic
    if game is not None:
        cfg["audio_mapping"]["game_ordinal"] = game
    if mixed is not None:
        cfg["audio_mapping"]["mixed_ordinal"] = mixed


def run_unattended(cfg: dict, video: str, name: str, mic=None, game=None, mixed=None) -> int:
    require_schedule_defaults(cfg)
    providers = cfg.get("providers") or {}
    require_provider(providers.get("translation"), "translation")
    require_provider(providers.get("repair"), "repair")
    cfg = json_copy(cfg)
    cfg.setdefault("unattended", {})
    cfg["unattended"]["enabled"] = True
    _ordinals(cfg, mic, game, mixed)
    from .config import resolve_path

    dest = resolve_path(cfg, cfg["jobs_dir"]) / name
    timings = []
    if not (dest / "manifest.json").is_file():
        t0 = time.perf_counter()
        code = _init(cfg, video, name)
        timings.append({"stage": "init", "seconds": round(time.perf_counter() - t0, 3), "exit": code})
        if code != 0:
            return code
    job = Job(job_path(cfg, name))
    # A job created by manual init does not have unattended enabled. Turn it on
    # in the snapshot so repair may use the configured shorter-translation budget.
    stored = job.config()
    stored.setdefault("unattended", {})
    stored["unattended"]["enabled"] = True
    if "providers" not in stored:
        stored["providers"] = providers
    write_json(job.dir / "config.json", {k: v for k, v in stored.items() if not str(k).startswith("_")})
    rounds = {"translation": 0, "repair": 0}
    limit = int(cfg["unattended"].get("max_shorter_translations", 2))
    for _ in range(12):
        t0 = time.perf_counter()
        code = run_job(job)
        job = Job(job.dir)
        timings.append({"stage": f"run:{job.state}", "seconds": round(time.perf_counter() - t0, 3), "exit": code})
        if code in {0, 3}:
            _write_timings(job, timings, rounds)
            return code
        if code == 1:
            _write_timings(job, timings, rounds)
            return 1
        if job.state == "awaiting_translation":
            rounds["translation"] += 1
            _handoff(job, "translation", providers["translation"], None)
            continue
        if job.state == "awaiting_repair":
            rounds["repair"] += 1
            if rounds["repair"] > limit:
                raise ProviderError(f"Repair provider was called more than {limit} times.")
            current = {int(s["id"]): s.get("english") or "" for s in job.data["timeline"]}
            _handoff(job, "repair", providers["repair"], current)
            continue
        _write_timings(job, timings, rounds)
        return code
    raise ProviderError("Unattended run exceeded its handoff rounds.")


def _init(cfg: dict, video: str, name: str) -> int:
    import argparse
    from .cli import cmd_init

    args = argparse.Namespace(
        config=None,
        video=video,
        name=name,
        mic_ordinal=cfg["audio_mapping"]["mic_ordinal"],
        game_ordinal=cfg["audio_mapping"]["game_ordinal"],
        mixed_ordinal=cfg["audio_mapping"]["mixed_ordinal"],
    )
    # cmd_init reloads config from disk. Write a temporary snapshot and pass it.
    root = Path(cfg["_project_root"])
    snap = root / "jobs" / f".{name}.init-config.json"
    snap.parent.mkdir(parents=True, exist_ok=True)
    payload = {k: v for k, v in cfg.items() if not str(k).startswith("_")}
    payload["unattended"] = dict(payload.get("unattended") or {})
    payload["unattended"]["enabled"] = True
    write_json(snap, payload)
    args.config = str(snap)
    from .config import load_config

    loaded = load_config(snap)
    loaded["source_video"] = str(Path(video).expanduser().resolve())
    # Call the same checks as cmd_init by delegating.
    args.config = str(snap)
    code = cmd_init(args)
    return code


def _handoff(job: Job, role: str, spec: dict, current: dict | None) -> None:
    t0 = time.perf_counter()
    if role == "translation":
        request = export_translation(job, job.config())
    else:
        request = export_repair(job)
    response = job.dir / "handoff" / f"{role}_provider_response.json"
    data = invoke_checked(spec, request, response, role, current)
    if role == "translation":
        accept_translation(job, response)
    else:
        accept_repair(job, response, revision_limit_n=int((job.config().get("unattended") or {}).get("max_shorter_translations", 2)))
    log = job.dir / "handoff" / "provider.log"
    with log.open("a", encoding="utf-8") as handle:
        handle.write(f"{role} ok in {time.perf_counter() - t0:.1f}s ids={len(data.get('segments') or [])}\n")


def _write_timings(job: Job, timings: list[dict], rounds: dict) -> None:
    stored = []
    path = job.dir / "report" / "timings.json"
    if path.is_file():
        stored = read_json(path).get("stages") or []
    write_json(path, {"stages": stored + timings, "provider_rounds": rounds})


def json_copy(cfg: dict) -> dict:
    import json
    return json.loads(json.dumps(cfg))
