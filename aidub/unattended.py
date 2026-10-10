"""One-command driver: init, run, provider handoffs, resume, validate."""

from __future__ import annotations

import time
from pathlib import Path

from .config import require_schedule_defaults, require_synthesis_ready
from .job import Job, JobLock
from .pipeline import (
    accept_repair,
    accept_translation,
    export_repair,
    export_translation,
    job_path,
    run_job,
)
from .providers import ProviderError, require_provider, validate_provider_config
from .batches import invoke_batches
from .util import read_json, write_json


def _ordinals(cfg: dict, mic, game, mixed) -> None:
    if mic is not None:
        cfg["audio_mapping"]["mic_ordinal"] = mic
    if game is not None:
        cfg["audio_mapping"]["game_ordinal"] = game
    if mixed is not None:
        cfg["audio_mapping"]["mixed_ordinal"] = mixed


def run_unattended(cfg: dict, video: str, name: str, mic=None, game=None, mixed=None) -> int:
    cfg = json_copy(cfg)
    _ordinals(cfg, mic, game, mixed)
    if not name.replace(".", "").replace("_", "").replace("-", "").isalnum():
        raise RuntimeError("Invalid job name")
    from .config import resolve_path
    dest = resolve_path(cfg, cfg["jobs_dir"]) / name
    timings = []
    rounds = {"translation": 0, "repair": 0}
    with JobLock(dest) as lock:
        if not (dest / "manifest.json").is_file():
            from .cli import cmd_init
            import argparse
            args = argparse.Namespace(video=video, name=name, mic_ordinal=mic, game_ordinal=game, mixed_ordinal=mixed)
            cfg.setdefault("unattended", {})["enabled"] = True
            code = cmd_init(args, cfg=cfg, lock=lock)
            if code:
                return code
        job = Job(dest)
        if Path(video).expanduser().resolve() != Path(job.data["video"]).resolve():
            raise RuntimeError("This job belongs to a different source video. Use its original path or a new job name.")
        stored = job.config()
        require_schedule_defaults(stored)
        stored.setdefault("unattended", {})["enabled"] = True
        providers = stored.get("providers") or cfg.get("providers") or {}
        stored["providers"] = providers
        write_json(job.dir / "config.json", {k: v for k, v in stored.items() if not str(k).startswith("_")})
        try:
            for role in ("translation", "repair"):
                validate_provider_config(require_provider(providers.get(role), role))
            for _ in range(int(stored["unattended"].get("max_handoff_rounds", 12))):
                t0 = time.perf_counter()
                code = run_job(job, lock=lock)
                job = Job(dest)
                timings.append({"stage": f"run:{job.state}", "seconds": round(time.perf_counter() - t0, 3), "exit": code})
                if code in {0, 1, 3}:
                    return code
                role = "translation" if job.state == "awaiting_translation" else "repair" if job.state == "awaiting_repair" else None
                if role is None:
                    return code
                rounds[role] += 1
                current = {int(s["id"]): s.get("english") or "" for s in job.data["timeline"]} if role == "repair" else None
                _handoff(job, role, providers[role], current)
            raise ProviderError("Unattended run exceeded configured max_handoff_rounds. Check job diagnostics.")
        except KeyboardInterrupt:
            job = Job(dest)
            if job.state in {"awaiting_translation", "awaiting_repair"}:
                job.error = "Interrupted during provider handoff; a call without a durable response has uncertain external completion/billing. Resume to recover matching responses."
                job.save()
            raise
        except ProviderError as exc:
            # Keep the handoff resumable while recording the failure durably.
            job.error = str(exc)
            job.data["provider_error"] = {"state": job.state, "message": str(exc), "time": time.time()}
            job.save()
            raise
        finally:
            _write_timings(Job(dest), timings, rounds)


def _handoff(job: Job, role: str, spec: dict, current: dict | None) -> None:
    t0 = time.perf_counter()
    request = export_translation(job, job.config()) if role == "translation" else export_repair(job)
    cfg = job.config()
    invoke_batches(spec, read_json(request), job.dir / "handoff", role, current, cfg,
                   before_invoke=lambda: require_synthesis_ready(cfg))
    response = job.dir / "handoff" / f"{role}_provider_response.json"
    if role == "translation":
        accept_translation(job, response)
    else:
        accept_repair(job, response, revision_limit_n=int((job.config().get("unattended") or {}).get("max_shorter_translations", 2)))
    with (job.dir / "handoff/provider.log").open("a", encoding="utf-8") as handle:
        handle.write(f"{role} accepted in {time.perf_counter() - t0:.1f}s ids={len(read_json(response)['segments'])}\n")


def _write_timings(job: Job, timings: list[dict], rounds: dict) -> None:
    stored = []
    path = job.dir / "report" / "timings.json"
    if path.is_file():
        stored = read_json(path).get("stages") or []
    from .metrics import provider_metrics
    write_json(path, {"stages": stored + timings, "provider_rounds_this_process": rounds,
                      "provider_totals": provider_metrics(job.dir)})


def json_copy(cfg: dict) -> dict:
    import json
    return json.loads(json.dumps(cfg))
