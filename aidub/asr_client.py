"""Long-lived Whisper process so each spoken line does not reload the model."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


class AsrClient:
    def __init__(self, python: str, model: str = "turbo", device: str = "cuda"):
        self.python = python
        self.model = model
        self.device = device
        self.proc: subprocess.Popen | None = None

    def start(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            return
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        root = Path(__file__).resolve().parents[1]
        env["PYTHONPATH"] = str(root) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        self.proc = subprocess.Popen(
            [self.python, "-m", "aidub.asr_worker", "--model", self.model, "--device", self.device],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        ready = self._read()
        if not ready.get("ready"):
            raise RuntimeError(f"Whisper worker was not ready: {ready}")

    def _read(self) -> dict:
        assert self.proc is not None and self.proc.stdout is not None
        while True:
            line = self.proc.stdout.readline()
            if not line:
                err = ""
                if self.proc.stderr is not None:
                    err = self.proc.stderr.read()[:2000]
                raise RuntimeError(f"Whisper worker stopped on {self.device}. {err}")
            if not line.strip() or not line.lstrip().startswith("{"):
                continue
            return json.loads(line)

    def transcribe(self, path: str, language: str = "") -> dict:
        if self.proc is None or self.proc.poll() is not None:
            self.start()
        assert self.proc is not None and self.proc.stdin is not None and self.proc.stdout is not None
        payload = json.dumps({"cmd": "transcribe", "path": path, "language": language or None})
        self.proc.stdin.write(payload + "\n")
        self.proc.stdin.flush()
        data = self._read()
        if data.get("error"):
            raise RuntimeError(str(data["error"]))
        return data

    def close(self) -> None:
        proc = self.proc
        self.proc = None
        if proc is None or proc.poll() is not None:
            return
        try:
            if proc.stdin is not None:
                proc.stdin.write(json.dumps({"cmd": "shutdown"}) + "\n")
                proc.stdin.flush()
            proc.wait(timeout=10)
        except Exception:
            proc.kill()


def whisper_python(whisper_bin: str) -> str:
    return str(Path(whisper_bin).resolve().parent / "python")
