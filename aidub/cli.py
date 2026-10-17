import argparse
import sys
from contextlib import nullcontext
from pathlib import Path

from .config import apply_preset, load_config, load_preset, preflight, require_schedule_defaults, resolve_path, new_job_config
from .job import Job, JobLock
from .pipeline import accept_repair, accept_translation, export_repair, export_translation, job_path, next_hint, run_job
from .providers import ProviderError
from .unattended import run_unattended
from .util import read_json


def _cfg(args):
    return load_config(Path(args.config) if getattr(args, "config", None) else None)


def _job(cfg, name: str) -> Job:
    return Job(job_path(cfg, name))


def cmd_init(args, *, cfg=None, lock=None) -> int:
    cfg = cfg if cfg is not None else _cfg(args)
    if getattr(args, "preset", None):
        cfg = apply_preset(cfg, load_preset(args.preset))
    cfg = new_job_config(cfg)
    video = Path(args.video).expanduser().resolve()
    if not video.is_file():
        print(f"Video not found: {video}", file=sys.stderr)
        return 1
    preflight(cfg, providers_needed=bool((cfg.get("unattended") or {}).get("enabled")))
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
    except (RuntimeError, OSError, ValueError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    name = args.name
    if not name.replace(".", "").replace("_", "").replace("-", "").isalnum():
        print("Job name must contain only letters, numbers, dot, underscore, or hyphen", file=sys.stderr)
        return 1
    dest = resolve_path(cfg, cfg["jobs_dir"]) / name
    if lock is not None and not lock.owns(dest):
        raise RuntimeError("init requires an active lock for this job")
    with (nullcontext(lock) if lock is not None else JobLock(dest)):
        if (dest / "manifest.json").exists():
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


def cmd_auto(args) -> int:
    cfg = _cfg(args)
    try:
        return run_unattended(
            cfg,
            args.video,
            args.name,
            mic=args.mic_ordinal,
            game=args.game_ordinal,
            mixed=args.mixed_ordinal,
            preset=args.preset,
        )
    except ProviderError as exc:
        print(str(exc), file=sys.stderr)
        return 1


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
        job = Job(job.dir)
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
        job = Job(job.dir)
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
        job = Job(job.dir)
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
        job = Job(job.dir)
        try:
            accept_repair(job, response)
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 1
    print(f"next: bin/aidub resume {job.data['job_id']}")
    return 0


def cmd_asr_compare(args) -> int:
    from .asr_compare import compare_models
    cfg = _cfg(args)
    job = _job(cfg, args.job)
    with JobLock(job.dir):
        job = Job(job.dir)
        path = compare_models(job, job.config(), [m.strip() for m in args.models.split(",") if m.strip()])
    print(path)
    return 0


def cmd_reference_asr(args) -> int:
    from .reference_trial import transcribe_reference
    transcribe_reference(_cfg(args), Path(args.wav).expanduser().resolve(), Path(args.out).expanduser().resolve())
    print(Path(args.out).expanduser().resolve())
    return 0


def cmd_reference_trial(args) -> int:
    from .reference_trial import generate_trial
    generate_trial(_cfg(args), Path(args.prompts).expanduser().resolve(), Path(args.out).expanduser().resolve())
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
    failed = [c for c in data.get("checks") or [] if c.get("required", True) and c.get("ok") is not True]
    for row in failed:
        print(f"FAIL {row['name']}: {row['detail']}")
    print(job.dir / "report/validation.md")
    return 0 if data.get("status") in {"complete", "partial"} and not failed else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="aidub", description="Agent-operated gameplay dubbing")
    p.add_argument("--config", default="", help="config JSON (otherwise AIDUB_CONFIG, local config, portable default)")
    sub = p.add_subparsers(dest="cmd", required=True)

    init = sub.add_parser("init", help="create a job from a video")
    init.add_argument("video")
    init.add_argument("--name", required=True)
    init.add_argument("--mic-ordinal", type=int)
    init.add_argument("--game-ordinal", type=int)
    init.add_argument("--mixed-ordinal", type=int)
    init.add_argument("--preset", default=None, help="overlay config/presets/NAME.json when creating the job (e.g. quality)")
    init.set_defaults(func=cmd_init)

    auto = sub.add_parser("auto", help="unattended init, provider handoffs, resume, and validate")
    auto.add_argument("video")
    auto.add_argument("--name", required=True)
    auto.add_argument("--mic-ordinal", type=int)
    auto.add_argument("--game-ordinal", type=int)
    auto.add_argument("--mixed-ordinal", type=int)
    auto.add_argument("--preset", default=None, help="overlay config/presets/NAME.json when creating the job (e.g. quality)")
    auto.set_defaults(func=cmd_auto)

    asr = sub.add_parser("asr-compare", help="compare Whisper models on a job's cues and second-pass spans")
    asr.add_argument("job")
    asr.add_argument("--models", default="turbo,large-v3")
    asr.set_defaults(func=cmd_asr_compare)

    ref_asr = sub.add_parser("reference-asr", help="transcribe a local reference WAV with word timestamps")
    ref_asr.add_argument("wav")
    ref_asr.add_argument("--out", required=True)
    ref_asr.set_defaults(func=cmd_reference_asr)

    ref_trial = sub.add_parser("reference-trial", help="generate three fresh voice takes from one configured reference")
    ref_trial.add_argument("--prompts", required=True)
    ref_trial.add_argument("--out", required=True)
    ref_trial.set_defaults(func=cmd_reference_trial)

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
    except (RuntimeError, OSError, ValueError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
