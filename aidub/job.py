import fcntl
import json
from pathlib import Path

from .util import atomic_write_text, read_json

STAGES = (
    "inspect",
    "extract",
    "transcribe",
    "translation",
    "schedule",
    "mix",
    "validate",
)
STATES = (
    "pending",
    "running",
    "awaiting_translation",
    "awaiting_repair",
    "failed",
    "partial",
    "complete",
)


def empty_manifest(job_id: str, video: str) -> dict:
    return {
        "schema": "aidub.job.v1",
        "job_id": job_id,
        "state": "pending",
        "video": video,
        "error": None,
        "stages": {name: {"status": "pending", "fingerprint": None, "outputs": {}} for name in STAGES},
        "timeline": [],
        "notes": [],
    }


class JobLock:
    def __init__(self, job_dir: Path):
        self.path = job_dir / "LOCK"
        self.fd = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fd = open(self.path, "a+")
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self.fd.close()
            raise RuntimeError(
                f"Job is locked ({self.path}). Another run is active. Wait, or remove a stale LOCK only if no process holds it."
            ) from exc
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.fd is not None:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
            self.fd.close()
            self.fd = None


class Job:
    def __init__(self, directory: Path):
        self.dir = directory
        self.manifest_path = directory / "manifest.json"
        self.data = read_json(self.manifest_path)

    @classmethod
    def create(cls, directory: Path, job_id: str, video: str, config: dict) -> "Job":
        directory.mkdir(parents=True, exist_ok=True)
        if any(directory.iterdir()):
            raise RuntimeError(f"Job directory already exists and is not empty: {directory}")
        atomic_write_text(directory / "config.json", json.dumps(config, ensure_ascii=False, indent=2) + "\n")
        atomic_write_text(
            directory / "manifest.json",
            json.dumps(empty_manifest(job_id, video), ensure_ascii=False, indent=2) + "\n",
        )
        return cls(directory)

    def save(self) -> None:
        atomic_write_text(self.manifest_path, json.dumps(self.data, ensure_ascii=False, indent=2) + "\n")

    @property
    def state(self) -> str:
        return self.data["state"]

    @state.setter
    def state(self, value: str) -> None:
        if value not in STATES:
            raise ValueError(value)
        self.data["state"] = value

    def stage(self, name: str) -> dict:
        return self.data["stages"][name]

    def set_stage(self, name: str, status: str, fingerprint: str | None = None, outputs: dict | None = None) -> None:
        cur = self.stage(name)
        cur["status"] = status
        if fingerprint is not None:
            cur["fingerprint"] = fingerprint
        if outputs is not None:
            cur["outputs"] = outputs
        self.save()

    def config(self) -> dict:
        cfg = read_json(self.dir / "config.json")
        cfg["_config_path"] = str((self.dir / "config.json").resolve())
        cfg["_project_root"] = str(Path(cfg.get("_project_root") or Path(__file__).resolve().parents[1]))
        return cfg
