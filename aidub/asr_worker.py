"""Only protocol JSON goes to stdout; library chatter and errors go to stderr."""
from __future__ import annotations

import argparse
import contextlib
import json
import sys
import traceback
from pathlib import Path


DECODE_OPTIONS = {"condition_on_previous_text", "beam_size", "best_of", "temperature", "initial_prompt", "patience",
                  "no_speech_threshold", "compression_ratio_threshold", "logprob_threshold", "hallucination_silence_threshold"}


def decode_options(raw) -> dict:
    options = {k: v for k, v in (raw or {}).items() if k in DECODE_OPTIONS}
    if isinstance(options.get("temperature"), list):
        options["temperature"] = tuple(float(t) for t in options["temperature"])
    return options


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()
    if not Path(args.model).is_file():
        raise RuntimeError("Whisper requires a pre-existing local weights file; downloads are disabled.")
    with contextlib.redirect_stdout(sys.stderr):
        import whisper
        model = whisper.load_model(args.model, device=args.device)
    def emit(data):
        sys.stdout.write(json.dumps(data, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    emit({"ready": True, "model": args.model, "device": args.device})
    for line in sys.stdin:
        msg = json.loads(line)
        if msg.get("cmd") == "shutdown":
            break
        try:
            with contextlib.redirect_stdout(sys.stderr):
                result = model.transcribe(msg["path"], fp16=args.device.startswith("cuda"), verbose=False,
                                          language=msg.get("language") or None,
                                          word_timestamps=bool(msg.get("word_timestamps")),
                                          **decode_options(msg.get("options")))
            emit(result if msg.get("full_result") else {"text": (result.get("text") or "").strip(), "language": result.get("language")})
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
            emit({"error": f"{type(exc).__name__}: {exc}"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
