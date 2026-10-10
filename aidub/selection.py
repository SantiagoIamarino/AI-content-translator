"""Best-of-N take features, pacing gates and ranking.

Scores combine measurable evidence only: speaking rate, internal pauses,
ASR agreement/confidence, distance from the reference voice and from takes
already chosen in this job, then tempo. Lower is better. These are proxies;
they do not establish perceived naturalness.
"""

from __future__ import annotations

import math

import numpy as np

from .audio import speech_bounds, to_mono
from .textnorm import english_syllables

DEFAULTS = {
    "candidates": 4,
    "max_extra_attempts": 4,
    "natural_rate_low": 3.8,
    "natural_rate_high": 6.5,
    "reject_rate_low": 2.3,
    "reject_rate_high": 9.0,
    "pause_soft_sec": 0.45,
    "pause_hard_sec": 1.0,
    "weights": {"pace": 3.0, "pause": 2.0, "voice_reference": 1.5, "voice_consistency": 1.5,
                "text": 2.0, "asr_confidence": 1.0, "tempo": 3.0},
}


def settings(cfg: dict) -> dict:
    block = cfg.get("voice_selection") or {}
    if not block.get("enabled"):
        return {}
    merged = dict(DEFAULTS)
    merged.update({k: v for k, v in block.items() if k != "weights"})
    merged["weights"] = dict(DEFAULTS["weights"], **(block.get("weights") or {}))
    merged["candidates"] = max(1, min(8, int(merged["candidates"])))
    merged["max_extra_attempts"] = max(0, min(8, int(merged["max_extra_attempts"])))
    return merged


def pacing(wav: np.ndarray, sr: int, text: str, rms_thr: float = 0.005, tempo: float = 1.0) -> dict:
    """Speaking rate over the voiced core and the longest internal pause."""
    mono = to_mono(wav) if np.asarray(wav).ndim > 1 else np.asarray(wav, dtype=np.float32)
    bounds = speech_bounds(mono, sr, rms_thr)
    syllables = english_syllables(text)
    if bounds is None or sr <= 0:
        return {"syllables": syllables, "core_sec": 0.0, "rate": None, "longest_pause_sec": 0.0, "pauses_over_soft": 0}
    first, last = bounds
    core = mono[first:last]
    win = max(1, int(sr * 0.02))
    n = core.size // win
    frames = core[: n * win].reshape(n, win) if n else core.reshape(1, -1)
    voiced = np.sqrt(np.mean(frames * frames, axis=1)) > rms_thr
    longest = run = 0
    gaps = []
    for flag in voiced:
        if flag:
            if run:
                gaps.append(run)
            run = 0
        else:
            run += 1
    longest = max(gaps, default=0) * win / sr / tempo
    core_sec = core.size / sr / tempo
    return {
        "syllables": syllables,
        "core_sec": round(core_sec, 4),
        "rate": round(syllables / core_sec, 3) if core_sec > 0 else None,
        "longest_pause_sec": round(longest, 3),
        "pauses_over_soft": int(sum(1 for g in gaps if g * win / sr / tempo > DEFAULTS["pause_soft_sec"])),
    }


def pacing_issues(info: dict, opts: dict) -> list[str]:
    issues = []
    if info["longest_pause_sec"] > float(opts.get("pause_hard_sec", DEFAULTS["pause_hard_sec"])):
        issues.append("pathological_pause")
    rate = info.get("rate")
    if rate is not None and info["syllables"] >= 4:
        if rate < float(opts.get("reject_rate_low", DEFAULTS["reject_rate_low"])) or rate > float(opts.get("reject_rate_high", DEFAULTS["reject_rate_high"])):
            issues.append("abnormal_rate")
    return issues


def _log_ratio(a, b) -> float | None:
    if not a or not b or a <= 0 or b <= 0:
        return None
    return abs(math.log(float(a) / float(b)))


def voice_distance(profile: dict, target: dict | None) -> float | None:
    if not target:
        return None
    parts = []
    for key, scale in (("f0", math.log(1.25)), ("centroid", math.log(1.35))):
        d = _log_ratio(profile.get(key), target.get(key))
        if d is not None:
            parts.append(d / scale)
    if not parts:
        return None
    return round(float(np.mean(parts)), 4)


def running_profile(chosen: list[dict]) -> dict | None:
    f0 = [c["f0"] for c in chosen if c.get("f0")]
    cent = [c["centroid"] for c in chosen if c.get("centroid")]
    if len(f0) < 3 and len(cent) < 3:
        return None
    return {"f0": float(np.median(f0)) if len(f0) >= 3 else None,
            "centroid": float(np.median(cent)) if len(cent) >= 3 else None}


def score_take(attempt: dict, pace: dict, reference: dict, running: dict | None, opts: dict) -> dict:
    w = opts["weights"]
    quality = attempt.get("quality") or {}
    speaker = quality.get("speaker") or {}
    components = {}
    rate = pace.get("rate")
    lo, hi = float(opts["natural_rate_low"]), float(opts["natural_rate_high"])
    if rate is None or pace["syllables"] < 3:
        components["pace"] = 0.0
    elif rate < lo:
        components["pace"] = math.log(lo / rate)
    elif rate > hi:
        components["pace"] = math.log(rate / hi)
    else:
        components["pace"] = 0.0
    components["pause"] = max(0.0, pace["longest_pause_sec"] - float(opts["pause_soft_sec"]))
    ref_d = voice_distance(speaker, reference)
    run_d = voice_distance(speaker, running)
    components["voice_reference"] = ref_d or 0.0
    components["voice_consistency"] = run_d or 0.0
    text = quality.get("text_check") or {}
    components["text"] = float(text.get("error_rate") or 0.0) + 0.3 * len(text.get("soft") or [])
    prob = quality.get("asr_mean_probability")
    components["asr_confidence"] = (1.0 - float(prob)) if prob is not None else 0.0
    components["tempo"] = max(0.0, float(attempt.get("tempo") or 1.0) - 1.0)
    total = sum(float(w[k]) * v for k, v in components.items())
    return {"score": round(total, 4), "components": {k: round(v, 4) for k, v in components.items()},
            "pacing": pace, "voice_distance_reference": ref_d, "voice_distance_running": run_d}


def choose(valid: list[dict]) -> dict:
    """Prefer placeable takes; among them the lowest score, then lower tempo, then earliest seed."""
    placed = [a for a in valid if a.get("placed")]
    pool = placed or valid
    return min(pool, key=lambda a: (a["selection"]["score"], float(a.get("tempo") or 1.0), int(a.get("seed") or 0)))
