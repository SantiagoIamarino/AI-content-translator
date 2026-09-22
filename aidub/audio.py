import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf


def read_audio(path: Path):
    wav, sr = sf.read(str(path), dtype="float32", always_2d=True)
    return wav, int(sr)


def write_wav(path: Path, wav: np.ndarray, sr: int, subtype: str = "PCM_16") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), wav, sr, subtype=subtype)


def to_mono(wav: np.ndarray) -> np.ndarray:
    if wav.ndim == 1:
        return np.asarray(wav, dtype=np.float32)
    return np.mean(wav, axis=1).astype(np.float32)


def metrics(wav: np.ndarray) -> dict:
    x = np.asarray(wav, dtype=np.float32)
    mono = to_mono(x) if x.ndim > 1 else x
    peak = float(np.max(np.abs(x))) if x.size else 0.0
    rms = float(np.sqrt(np.mean(np.square(mono)))) if mono.size else 0.0
    n_clip = int(np.sum(np.abs(x) >= 0.999))
    return {
        "n_samples": int(mono.size),
        "peak": peak,
        "rms": rms,
        "finite": bool(np.isfinite(x).all()) if x.size else True,
        "silent": rms < 1e-4,
        "clipping_samples": n_clip,
    }


def voiced_mask(wav: np.ndarray, sr: int, rms_thr: float = 0.005, win_sec: float = 0.01) -> np.ndarray:
    mono = to_mono(wav)
    if mono.size == 0:
        return np.zeros(0, dtype=bool)
    win = max(1, int(sr * win_sec))
    energy = np.convolve(mono * mono, np.ones(win) / win, mode="same")
    return energy > (rms_thr ** 2)


def trim_silence(wav: np.ndarray, sr: int, rms_thr: float, pad_ms: float) -> tuple[np.ndarray, int, int]:
    if wav.size == 0:
        return wav, 0, 0
    win = max(1, int(sr * 0.01))
    pad = int(sr * pad_ms / 1000.0)
    energy = np.convolve(wav * wav, np.ones(win) / win, mode="same")
    voiced = energy > (rms_thr ** 2)
    if not np.any(voiced):
        return wav, 0, 0
    first = int(np.argmax(voiced))
    last = int(len(wav) - 1 - np.argmax(voiced[::-1]))
    start = max(0, first - pad)
    end = min(len(wav), last + pad + 1)
    return wav[start:end].copy(), start, len(wav) - end


def resample_audio(wav: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
    if src_sr == dst_sr:
        return np.asarray(wav, dtype=np.float32)
    import torch
    import torchaudio

    tensor = torch.from_numpy(np.asarray(wav, dtype=np.float32)).unsqueeze(0)
    out = torchaudio.functional.resample(tensor, src_sr, dst_sr)
    return out.squeeze(0).numpy().astype(np.float32)


def atempo(ffmpeg: str, src: Path, dst: Path, tempo: float) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(src),
        "-filter:a", f"atempo={tempo:.6f}",
        str(dst),
    ]
    subprocess.run(cmd, check=True)


def mix_game_and_voice(game: np.ndarray, voice_mono: np.ndarray, limiter: float = 0.99) -> tuple[np.ndarray, dict]:
    if game.ndim != 2 or game.shape[1] != 2:
        raise RuntimeError(f"Game audio must be stereo, got {getattr(game, 'shape', None)}")
    if voice_mono.shape[0] != game.shape[0]:
        raise RuntimeError("Voice and game lengths differ; refusing to trim gameplay to the voice.")
    centered = np.stack([voice_mono, voice_mono], axis=1)
    raw = game.astype(np.float32) + centered.astype(np.float32)
    peak = float(np.max(np.abs(raw))) if raw.size else 0.0
    gain = 1.0
    if peak > limiter:
        gain = limiter / peak
    mixed = raw * gain
    info = {
        "game_peak": float(np.max(np.abs(game))) if game.size else 0.0,
        "voice_peak": float(np.max(np.abs(voice_mono))) if voice_mono.size else 0.0,
        "sum_peak_before_gain": peak,
        "gain": gain,
        "mix_peak": float(np.max(np.abs(mixed))) if mixed.size else 0.0,
        "clipping_samples": int(np.sum(np.abs(mixed) >= 0.999)),
        "voice_placement": "copied to L and R at full amplitude, not attenuated by 1/sqrt(2)",
    }
    return mixed.astype(np.float32), info
