"""Per-line candidate ledger and checkpoints.

A checkpoint is valid only for the same English text and reference recording.
Resume reuses it instead of synthesizing that candidate again.
"""

from __future__ import annotations

import json
from pathlib import Path

from .util import write_json


def ledger_path(job_dir: Path) -> Path:
    return job_dir / "ledger" / "candidates.jsonl"


def checkpoint_path(job_dir: Path, seg_id: int) -> Path:
    return job_dir / "checkpoints" / f"segment_{int(seg_id):04d}.json"


def append_candidate(job_dir: Path, record: dict) -> None:
    path = ledger_path(job_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def write_checkpoint(job_dir: Path, seg_id: int, record: dict) -> None:
    write_json(checkpoint_path(job_dir, seg_id), record)


def read_checkpoint(job_dir: Path, seg_id: int) -> dict | None:
    path = checkpoint_path(job_dir, seg_id)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def checkpoint_matches(record: dict | None, english: str, reference_sha256: str, checker: str | None = None) -> bool:
    if not record:
        return False
    if (record.get("english") or "") != (english or ""):
        return False
    if record.get("reference_sha256") != reference_sha256:
        return False
    if checker is not None and record.get("checker") != checker:
        return False
    return True


def cached_candidate(record: dict | None, text: str, seed: int) -> dict | None:
    if not record:
        return None
    for row in record.get("candidates") or []:
        if row.get("text") == text and int(row.get("seed", -1)) == int(seed) and row.get("quality") is not None:
            wav = row.get("wav")
            if wav and Path(wav).is_file():
                return row
    return None
