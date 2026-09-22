import argparse
import sys
from pathlib import Path

from .config import load_config, require_schedule_defaults, resolve_path
from .job import Job, JobLock
from .pipeline import accept_repair, accept_translation, export_repair, export_translation, job_path, next_hint, run_job
from .util import read_json


def _cfg(args):
    return load_config(Path(args.config) if getattr(args, "config", None) else None)


def _job(cfg, name: str) -> Job:
    return Job(job_path(cfg, name))


def cmd_init(args) -> int:
    cfg = _cfg(args)
    video = Path(args.video).expanduser().resolve()
    if not video.is_file():
        print(f"Video not found: {video}", file=sys.stderr)
        return 1
    for key, label in (
        ("python_qwen", "Qwen Python"),
        ("whisper", "Whisper"),
        ("ffmpeg", "ffmpeg"),
        ("ffprobe", "ffprobe"),
    ):
        if not Path(cfg["executables"][key]).is_file():
            print(f"{label} not found: {cfg['executables'][key]}", file=sys.stderr)
            return 1
    ref = resolve_path(cfg, cfg["reference"]["wav"])
    if not ref.is_file():
        print(f"Reference wav not found: {ref}", file=sys.stderr)
        return 1
    if args.mic_ordinal is not None:
        cfg["audio_mapping"]["mic_ordinal"] = args.mic_ordinal
    if args.game_ordinal is not None:
        cfg["audio_mapping"]["game_ordinal"] = args.game_ordinal
    if args.mixed_ordinal is not None:
        cfg["audio_mapping"]["mixed_ordinal"] = args.mixed_ordinal
    ordinals = [cfg["audio_mapping"][k] for k in ("mic_ordinal", "game_ordinal", "mixed_ordinal")]
    if len(set(ordinals)) < 3:
        print("mic, game, and mixed ordinals must be distinct", file=sys.stderr)
        return 1
    try:
        require_schedule_defaults(cfg)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    name = args.name
    if not name.replace(".", "").replace("_", "").replace("-", "").isalnum():
        print("Job name must contain only letters, numbers, dot, underscore, or hyphen", file=sys.stderr)
        return 1
    dest = resolve_path(cfg, cfg["jobs_dir"]) / name
    if dest.exists():
        print(f"Job already exists: {dest}. Choose another --name or resume it.", file=sys.stderr)
        return 1
    cfg["source_video"] = str(video)
    Job.create(dest, name, str(video), cfg)
    print(f"created {dest}")
    print(f"next: bin/aidub run {name}")
    return 0


def cmd_run(args) -> int:
    cfg = _cfg(args)
    return run_job(_job(cfg, args.job))


def cmd_status(args) -> int:
    cfg = _cfg(args)
    job = _job(cfg, args.job)
    print(f"STATE {job.state}")
    if job.data.get("error"):
        print(f"ERROR {job.data['error']}")
    for name, stage in job.data["stages"].items():
        print(f"  {name}: {stage['status']}")
    print(next_hint(job))
    return 0


def cmd_export_translation(args) -> int:
    cfg = _cfg(args)
    job = _job(cfg, args.job)
    with JobLock(job.dir):
        path = export_translation(job, job.config())
    print(path)
    return 0


def cmd_accept_translation(args) -> int:
    cfg = _cfg(args)
    job = _job(cfg, args.job)
    response = Path(args.response).expanduser().resolve()
    if not response.is_file():
        print(f"Response not found: {response}", file=sys.stderr)
        return 1
    with JobLock(job.dir):
        try:
            accept_translation(job, response)
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 1
    print(f"next: bin/aidub resume {job.data['job_id']}")
    return 0


def cmd_export_repair(args) -> int:
    cfg = _cfg(args)
    job = _job(cfg, args.job)
    with JobLock(job.dir):
        try:
            path = export_repair(job)
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 1
    print(path)
    return 0


def cmd_accept_repair(args) -> int:
    cfg = _cfg(args)
    job = _job(cfg, args.job)
    response = Path(args.response).expanduser().resolve()
    if not response.is_file():
        print(f"Response not found: {response}", file=sys.stderr)
        return 1
    with JobLock(job.dir):
        try:
            accept_repair(job, response)
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 1
    print(f"next: bin/aidub resume {job.data['job_id']}")
    return 0


def cmd_validate(args) -> int:
    cfg = _cfg(args)
    job = _job(cfg, args.job)
    report = job.dir / "report/validation.json"
    if not report.is_file():
        print("No validation report yet. Run the job first.", file=sys.stderr)
        return 1
    data = read_json(report)
    print(f"STATE {job.state}")
    print(f"ENGLISH_VIDEO {data.get('english_video')}")
    failed = [c for c in data.get("checks") or [] if not c.get("ok")]
    for row in failed:
        print(f"FAIL {row['name']}: {row['detail']}")
    print(job.dir / "report/validation.md")
    return 0 if data.get("status") in {"complete", "partial"} and not failed else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="aidub", description="Agent-operated gameplay dubbing")
    p.add_argument("--config", default="", help="config JSON (default: config/default.json)")
    sub = p.add_subparsers(dest="cmd", required=True)

    init = sub.add_parser("init", help="create a job from a video")
    init.add_argument("video")
    init.add_argument("--name", required=True)
    init.add_argument("--mic-ordinal", type=int)
    init.add_argument("--game-ordinal", type=int)
    init.add_argument("--mixed-ordinal", type=int)
    init.set_defaults(func=cmd_init)

    run = sub.add_parser("run", help="run ready stages until done or a handoff")
    run.add_argument("job")
    run.set_defaults(func=cmd_run)

    resume = sub.add_parser("resume", help="continue a job without repeating valid stages")
    resume.add_argument("job")
    resume.set_defaults(func=cmd_run)

    status = sub.add_parser("status", help="show job state")
    status.add_argument("job")
    status.set_defaults(func=cmd_status)

    exp = sub.add_parser("export-translation", help="write the translation request")
    exp.add_argument("job")
    exp.set_defaults(func=cmd_export_translation)

    acc = sub.add_parser("accept-translation", help="validate and store a translation response")
    acc.add_argument("job")
    acc.add_argument("response")
    acc.set_defaults(func=cmd_accept_translation)

    rx = sub.add_parser("export-repair", help="write the repair request for unplaced lines")
    rx.add_argument("job")
    rx.set_defaults(func=cmd_export_repair)

    ar = sub.add_parser("accept-repair", help="validate and store a repair response")
    ar.add_argument("job")
    ar.add_argument("response")
    ar.set_defaults(func=cmd_accept_repair)

    val = sub.add_parser("validate", help="show the validation report")
    val.add_argument("job")
    val.set_defaults(func=cmd_validate)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.config == "":
        args.config = None
    try:
        return int(args.func(args))
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
