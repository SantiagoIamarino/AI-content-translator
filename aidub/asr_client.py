"""Whisper JSON-lines process with file-backed diagnostics and bounded waits."""
from __future__ import annotations

import json
import os
import queue
import subprocess
import tempfile
import threading
from pathlib import Path


class AsrClient:
    def __init__(self, python: str, model: str = "turbo", device: str = "cuda", *,
                 log_path: Path | None = None, startup_timeout: float = 180,
                 request_timeout: float = 180, worker_command: list[str] | None = None):
        self.python, self.model, self.device = python, model, device
        self.log_path = log_path
        self.startup_timeout, self.request_timeout = startup_timeout, request_timeout
        self.worker_command = worker_command
        self.proc = None
        self._stderr = None
        self._lines = queue.Queue(maxsize=256)
        self._reader = None
        self._reader_stop = threading.Event()

    def _diagnostic(self) -> str:
        if self._stderr is None:
            return ""
        self._stderr.flush()
        # Read through a separate descriptor without moving the worker's offset.
        if self.log_path:
            with self.log_path.open("rb") as handle:
                handle.seek(max(0, self.log_path.stat().st_size - 8000))
                return handle.read().decode("utf-8", "replace")
        size = os.fstat(self._stderr.fileno()).st_size
        return os.pread(self._stderr.fileno(), min(size, 8000), max(0, size - 8000)).decode("utf-8", "replace")

    def start(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            return
        if self.proc is not None:
            self.close()
        env = os.environ.copy()
        env.update(PYTHONUNBUFFERED="1", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
        root = Path(__file__).resolve().parents[1]
        env["PYTHONPATH"] = str(root) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        if self.log_path:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            self._stderr = self.log_path.open("ab", buffering=0)
        else:
            self._stderr = tempfile.TemporaryFile("w+b")
        command = self.worker_command or [self.python, "-m", "aidub.asr_worker", "--model", self.model, "--device", self.device]
        self.proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=self._stderr, text=True, env=env)
        self._lines = queue.Queue(maxsize=256)
        self._reader_stop = threading.Event()
        stream, lines = self.proc.stdout, self._lines
        stopped = self._reader_stop
        def deliver(line):
            while not stopped.is_set():
                try:
                    lines.put(line, timeout=0.2)
                    return
                except queue.Full:
                    continue
        def drain():
            try:
                for line in stream:
                    if stopped.is_set():
                        break
                    deliver(line)
            finally:
                deliver(None)
        self._reader = threading.Thread(target=drain, daemon=True)
        self._reader.start()
        try:
            ready = self._read(self.startup_timeout)
            if not ready.get("ready"):
                raise RuntimeError(f"Whisper worker was not ready: {ready}")
        except Exception:
            self.close()
            raise

    def _read(self, timeout: float | None = None) -> dict:
        try:
            line = self._lines.get(timeout=timeout or self.request_timeout)
        except queue.Empty:
            detail = self._diagnostic()
            self.close(force=True)
            raise RuntimeError(f"Whisper worker timed out on {self.device}. Log: {self.log_path}. {detail}")
        if line is None:
            raise RuntimeError(f"Whisper worker stopped on {self.device}. Log: {self.log_path}. {self._diagnostic()}")
        try:
            data = json.loads(line)
            if not isinstance(data, dict):
                raise ValueError("JSON object expected")
            return data
        except ValueError as exc:
            raise RuntimeError(f"Invalid worker JSON protocol: {line[:500]}. {self._diagnostic()}") from exc

    def transcribe(self, path: str, language: str = "", *, word_timestamps=False,
                   full_result=False, timeout: float | None = None, options: dict | None = None) -> dict:
        if self.proc is None or self.proc.poll() is not None:
            self.start()
        payload = {"cmd": "transcribe", "path": path, "language": language or None,
                   "word_timestamps": word_timestamps, "full_result": full_result}
        if options:
            payload["options"] = options
        try:
            self.proc.stdin.write(json.dumps(payload) + "\n")
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise RuntimeError(f"Whisper worker pipe failed. {self._diagnostic()}") from exc
        data = self._read(timeout)
        if data.get("error"):
            raise RuntimeError(f"{data['error']}. Log: {self.log_path}. {self._diagnostic()}")
        return data

    def close(self, *, force=False) -> None:
        proc, self.proc = self.proc, None
        interrupted = None
        if proc is not None:
            if proc.poll() is None and force:
                proc.kill()
                proc.wait(timeout=5)
            elif proc.poll() is None:
                try:
                    proc.stdin.write('{"cmd":"shutdown"}\n')
                    proc.stdin.flush()
                    proc.wait(timeout=10)
                except BaseException as exc:
                    proc.kill()
                    proc.wait(timeout=5)
                    if not isinstance(exc, Exception):
                        interrupted = exc
            if proc.stdin:
                proc.stdin.close()
            if self._reader:
                self._reader_stop.set()
                self._reader.join(timeout=2)
            if proc.stdout:
                proc.stdout.close()
        if self._stderr:
            self._stderr.close()
            self._stderr = None
        if interrupted is not None:
            raise interrupted


def whisper_python(whisper_bin: str) -> str:
    # Keep the virtualenv interpreter adjacent to the configured entry point.
    return str(Path(whisper_bin).absolute().parent / "python")
