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


def speech_bounds(wav: np.ndarray, sr: int, rms_thr: float = 0.005, win_sec: float = 0.01) -> tuple[int, int] | None:
    mono = to_mono(wav) if np.asarray(wav).ndim > 1 else np.asarray(wav, dtype=np.float32)
    mono = np.asarray(mono, dtype=np.float32)
    if mono.size == 0 or sr <= 0:
        return None
    win = max(1, int(sr * win_sec))
    energy = np.convolve(mono * mono, np.ones(win) / win, mode="same")
    voiced = np.flatnonzero(energy > (rms_thr ** 2))
    if voiced.size == 0:
        return None
    return int(voiced[0]), int(voiced[-1]) + 1


def _cosine_up(n: int) -> np.ndarray:
    if n <= 0:
        return np.zeros(0, dtype=np.float32)
    i = np.arange(n, dtype=np.float32)
    return (0.5 - 0.5 * np.cos(np.pi * (i + 1.0) / n)).astype(np.float32)


def render_voice_with_margins(
    wav: np.ndarray,
    sr: int,
    *,
    rms_thr: float = 0.005,
    lead_ms: float = 20.0,
    tail_ms: float = 60.0,
    fade_ms: float = 12.0,
    target_rms: float | None = None,
    min_gain: float = 0.6,
    max_gain: float = 1.8,
    peak_limit: float = 0.98,
) -> tuple[np.ndarray, dict]:
    """Keep a quiet margin around the RMS core and fade only that margin.

    The timed core is not attenuated, so a consonant that begins at the
    energy onset stays intact. Loudness gain is applied to the whole piece.
    """
    mono = to_mono(wav) if np.asarray(wav).ndim > 1 else np.asarray(wav, dtype=np.float32)
    mono = np.asarray(mono, dtype=np.float32)
    bounds = speech_bounds(mono, sr, rms_thr)
    info = {
        "had_core": bounds is not None,
        "lead_ms_used": 0.0,
        "tail_ms_used": 0.0,
        "gain": 1.0,
        "edge": "no_speech",
        "core_lo": 0,
        "core_hi": 0,
    }
    if bounds is None:
        return mono[:0].copy(), info
    first, last = bounds
    lead_n = max(0, int(round(sr * lead_ms / 1000.0)))
    tail_n = max(0, int(round(sr * tail_ms / 1000.0)))
    fade_n = max(0, int(round(sr * fade_ms / 1000.0)))
    start = max(0, first - lead_n)
    end = min(mono.size, last + tail_n)
    piece = mono[start:end].copy()
    core_lo = first - start
    core_hi = last - start
    core = piece[core_lo:core_hi]
    core_before = core.copy()
    core_rms = float(np.sqrt(np.mean(np.square(core)))) if core.size else 0.0
    gain = 1.0
    if target_rms and core_rms > 1e-4:
        gain = float(np.clip(float(target_rms) / core_rms, min_gain, max_gain))
    piece *= gain
    peak = float(np.max(np.abs(piece))) if piece.size else 0.0
    if peak > peak_limit > 0:
        piece *= peak_limit / peak
        gain *= peak_limit / peak
    env = np.ones(piece.size, dtype=np.float32)
    if core_lo > 0:
        env[:core_lo] = _cosine_up(core_lo)
        info["lead_ms_used"] = 1000.0 * core_lo / sr
    tail = piece.size - core_hi
    if tail > 0:
        fn = min(fade_n, tail)
        if fn > 0:
            env[-fn:] = np.minimum(env[-fn:], _cosine_up(fn)[::-1])
        info["tail_ms_used"] = 1000.0 * tail / sr
    piece *= env
    info.update({
        "gain": float(gain),
        "core_rms_before": core_rms,
        "edge": "margin_fade" if (core_lo > 0 or tail > 0) else "core_only",
        "core_lo": int(core_lo),
        "core_hi": int(core_hi),
        "duration_sec": piece.size / float(sr) if sr else 0.0,
        "core_preserved": bool(core_before.size == 0 or np.allclose(piece[core_lo:core_hi], core_before * gain, atol=1e-5)),
    })
    return piece, info


def safety_fade(wav: np.ndarray, sr: int, fade_ms: float = 8.0, guard: float = 0.2) -> tuple[np.ndarray, dict]:
    """Short edge ramp that stops before a loud consonant sample."""
    x = np.asarray(wav, dtype=np.float32).copy()
    if x.ndim > 1:
        x = to_mono(x)
    if x.size == 0 or sr <= 0:
        return x, {"edge": "empty"}
    peak = float(np.max(np.abs(x))) + 1e-9
    n = max(1, int(round(sr * fade_ms / 1000.0)))
    env = np.ones(x.size, dtype=np.float32)
    ramp = _cosine_up(n)
    for i in range(min(n, x.size)):
        if abs(float(x[i])) >= guard * peak:
            break
        env[i] = ramp[i]
    for i in range(min(n, x.size)):
        j = x.size - 1 - i
        if abs(float(x[j])) >= guard * peak:
            break
        env[j] = min(float(env[j]), float(ramp[i]))
    return x * env, {"edge": "safety_fade", "fade_ms": fade_ms}


def margin_budget_ms(core_sec: float, window_sec: float, lead_ms: float, tail_ms: float, lead_room_ms: float) -> tuple[float, float]:
    """Fit quiet margins into leftover time. Tail is dropped before the lead."""
    tail_room_ms = max(0.0, (window_sec - core_sec) * 1000.0)
    lead = min(max(0.0, lead_ms), max(0.0, lead_room_ms))
    tail = min(max(0.0, tail_ms), tail_room_ms)
    return lead, tail


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
