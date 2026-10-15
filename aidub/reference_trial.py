"""Local reference transcription and controlled, fresh voice trials."""
from __future__ import annotations

import json
from pathlib import Path

from .asr_client import AsrClient, whisper_python
from .config import executable, preflight, reference_text, resolve_path, require_schedule_defaults, whisper_model_file
from .synth import QwenBackend
from .util import sha256_file, sha256_bytes, write_json


def transcribe_reference(cfg: dict, wav: Path, out: Path) -> None:
    if not wav.is_file():
        raise RuntimeError(f"Reference WAV not found: {wav}")
    if out.exists():
        raise RuntimeError(f"Output already exists: {out}")
    out.parent.mkdir(parents=True, exist_ok=True)
    client = AsrClient(whisper_python(executable(cfg, "whisper")), str(whisper_model_file(cfg)),
                       cfg["whisper"]["device"], log_path=out.with_suffix(".log"), request_timeout=300)
    try:
        result = client.transcribe(str(wav), language="English", word_timestamps=True, full_result=True,
                                   options={"condition_on_previous_text": False, "beam_size": 5, "best_of": 5})
    finally:
        client.close()
    write_json(out, {"wav": str(wav), "wav_sha256": sha256_file(wav), "model": str(whisper_model_file(cfg)),
                     "decode_options": {"language": "English", "condition_on_previous_text": False,
                                        "beam_size": 5, "best_of": 5}, "result": result})


def generate_trial(cfg: dict, prompts_path: Path, out: Path) -> None:
    require_schedule_defaults(cfg)
    preflight(cfg, providers_needed=False)
    prompts = json.loads(prompts_path.read_text(encoding="utf-8"))
    if not isinstance(prompts, list) or len(prompts) != 3 or not all(isinstance(x, str) and x.strip() for x in prompts):
        raise RuntimeError("Trial prompts must be a JSON list of exactly three nonempty strings")
    if out.exists():
        raise RuntimeError(f"Trial output already exists: {out}; choose a new directory for fresh takes")
    ref_wav = resolve_path(cfg, cfg["reference"]["wav"])
    ref_text = reference_text(cfg)
    out.mkdir(parents=True)
    manifest = {"reference_wav": str(ref_wav), "reference_wav_sha256": sha256_file(ref_wav),
                "reference_text_file": str(resolve_path(cfg, cfg["reference"]["text_file"])),
                "reference_text_sha256": sha256_bytes(ref_text.encode()), "reference_text": ref_text,
                "qwen3": cfg["qwen3"], "prompts": prompts, "takes": []}
    write_json(out / "manifest.json", manifest)
    backend = QwenBackend(cfg)
    for index, prompt in enumerate(prompts, start=1):
        seed = 5100 + index
        wav = out / f"phrase_{index:02d}_seed_{seed}.wav"
        meta = backend.synthesize(prompt, str(ref_wav), ref_text, str(wav), seed)
        manifest["takes"].append({"index": index, "seed": seed, "prompt": prompt,
                                  "wav": str(wav), "wav_sha256": meta["waveform_sha256"],
                                  "duration_sec": meta["duration_sec"], "inference_seconds": meta["inference_seconds"]})
        write_json(out / "manifest.json", manifest)
        print(f"trial {index}/3: {wav} ({meta['duration_sec']:.2f} s)", flush=True)
