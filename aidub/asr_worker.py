"""Whisper Turbo worker. Launch with the Whisper interpreter, not the Qwen one.

Stdin and stdout are JSON lines. The model stays loaded until shutdown.
"""

from __future__ import annotations

import argparse
import json
import sys


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="turbo")
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()
    import whisper

    model = whisper.load_model(args.model, device=args.device)
    sys.stdout.write(json.dumps({"ready": True, "device": args.device, "model": args.model}) + "\n")
    sys.stdout.flush()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        msg = json.loads(line)
        if msg.get("cmd") == "shutdown":
            break
        path = msg["path"]
        language = msg.get("language") or None
        try:
            kwargs = {"fp16": args.device.startswith("cuda"), "verbose": False}
            if language:
                kwargs["language"] = language
            result = model.transcribe(path, **kwargs)
            text = (result.get("text") or "").strip()
            payload = {"text": text, "language": result.get("language") or language}
        except Exception as exc:
            payload = {"error": f"{type(exc).__name__}: {exc}"}
        sys.stdout.write(json.dumps(payload) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
