import json
import time
from pathlib import Path

import numpy as np

from .audio import metrics, write_wav
from .schedule import synth_cache_key
from .util import read_json, write_json


class QwenBackend:
    def __init__(self, cfg: dict):
        import torch
        from qwen_tts import Qwen3TTSModel

        if not torch.cuda.is_available():
            raise RuntimeError("CUDA is not available; refusing CPU fallback.")
        q = cfg["qwen3"]
        if q["x_vector_only_mode"] is not False:
            raise RuntimeError("x_vector_only_mode must be false.")
        self.torch = torch
        self.generation = dict(q["generation"])
        self.language = q["language"]
        self.model_id = q["model_id"]
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()
        t0 = time.perf_counter()
        self.model = Qwen3TTSModel.from_pretrained(
            q["model_id"],
            device_map=q["device"],
            dtype=torch.bfloat16,
            attn_implementation=q["attn_implementation"],
        )
        torch.cuda.synchronize()
        self.load_seconds = time.perf_counter() - t0
        self.load_peak_gpu_gib = torch.cuda.max_memory_allocated() / (1024 ** 3)
        params_on_cuda = sum(p.numel() for p in self.model.model.parameters() if p.is_cuda)
        if params_on_cuda == 0:
            raise RuntimeError("Model parameters are not on CUDA; refusing CPU fallback.")
        attn = getattr(self.model.model.config, "_attn_implementation", None)
        if attn != q["attn_implementation"]:
            raise RuntimeError(f"Attention implementation is {attn}, expected {q['attn_implementation']}")
        self.prompt = None
        self.prompt_key = None
        self.prompt_seconds = 0.0

    def voice_prompt(self, reference_audio: str, reference_text: str):
        key = (str(reference_audio), reference_text)
        if self.prompt is not None and self.prompt_key == key:
            return self.prompt
        t0 = time.perf_counter()
        self.prompt = self.model.create_voice_clone_prompt(
            ref_audio=str(reference_audio),
            ref_text=reference_text,
            x_vector_only_mode=False,
        )
        self.torch.cuda.synchronize()
        self.prompt_seconds += time.perf_counter() - t0
        self.prompt_key = key
        modes = [getattr(it, "x_vector_only_mode", None) for it in self.prompt]
        if any(m is True for m in modes):
            raise RuntimeError("Voice clone prompt is x-vector-only; refusing.")
        return self.prompt

    def synthesize(self, text: str, reference_audio: str, reference_text: str, output_path: str, seed: int) -> dict:
        from transformers import set_seed

        out = Path(output_path)
        prompt = self.voice_prompt(reference_audio, reference_text)
        set_seed(int(seed))
        self.torch.cuda.manual_seed_all(int(seed))
        self.torch.cuda.reset_peak_memory_stats()
        t0 = time.perf_counter()
        wavs, sr = self.model.generate_voice_clone(
            text=text,
            language=self.language,
            voice_clone_prompt=prompt,
            **self.generation,
        )
        self.torch.cuda.synchronize()
        infer_s = time.perf_counter() - t0
        wav = np.asarray(wavs[0], dtype=np.float32)
        if wav.ndim > 1:
            wav = wav.mean(axis=1).astype(np.float32)
        write_wav(out, wav, int(sr), subtype="FLOAT")
        info = metrics(wav)
        if not info["finite"] or info["silent"]:
            raise RuntimeError(f"Synthesis unusable for {text!r}: {info}")
        meta = {
            "path": str(out),
            "text": text,
            "reference_audio": str(reference_audio),
            "seed": int(seed),
            "sample_rate": int(sr),
            "duration_sec": info["n_samples"] / int(sr),
            "inference_seconds": infer_s,
            "peak_gpu_gib": self.torch.cuda.max_memory_allocated() / (1024 ** 3),
            "mode": "generate_voice_clone",
            "x_vector_only_mode": False,
            "language": self.language,
            "generation_settings": self.generation,
            "cache_hit": False,
            **info,
        }
        write_json(out.with_suffix(".json"), meta)
        return meta


def cache_paths(cache_dir: Path, key: str) -> tuple[Path, Path]:
    return cache_dir / f"{key}.wav", cache_dir / f"{key}.json"


def lookup_cache(cache_dir: Path, key: str, text: str, seed: int) -> dict | None:
    wav, meta_path = cache_paths(cache_dir, key)
    if not wav.is_file() or not meta_path.is_file():
        return None
    meta = read_json(meta_path)
    if meta.get("text") != text or int(meta.get("seed", -1)) != int(seed):
        return None
    if not meta.get("finite", True) or meta.get("silent", False):
        return None
    meta = dict(meta)
    meta["path"] = str(wav)
    meta["cache_hit"] = True
    meta["inference_seconds"] = 0.0
    return meta


def store_cache(cache_dir: Path, key: str, meta: dict) -> dict:
    cache_dir.mkdir(parents=True, exist_ok=True)
    src = Path(meta["path"])
    wav, meta_path = cache_paths(cache_dir, key)
    if src.resolve() != wav.resolve():
        wav.write_bytes(src.read_bytes())
    stored = dict(meta)
    stored["path"] = str(wav)
    stored["cache_key"] = key
    write_json(meta_path, stored)
    return stored


def synthesize_cached(backend: QwenBackend | None, cache_dir: Path, cfg: dict, text: str, ref_wav: str, ref_text: str, ref_sha: str, seed: int) -> dict:
    key = synth_cache_key(text, ref_sha, ref_text, seed, cfg["qwen3"])
    hit = lookup_cache(cache_dir, key, text, seed)
    if hit is not None:
        hit["cache_key"] = key
        return hit
    if backend is None:
        raise RuntimeError(f"No synthesis cache for seed {seed}. A model load is required.")
    raw = cache_dir / f"{key}.wav"
    meta = backend.synthesize(text, ref_wav, ref_text, str(raw), seed)
    meta["cache_key"] = key
    write_json(raw.with_suffix(".json"), meta)
    return meta
