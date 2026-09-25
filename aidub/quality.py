"""Waveform, speaker, and transcript checks for one synthesized candidate.

A single speaker measurement on a short phrase is never enough to reject it.
Wrong-speaker rejection requires two independent features (for very short
clips, fundamental frequency is ignored because it is unstable).
"""

from __future__ import annotations

import re

import numpy as np

from .audio import speech_bounds, to_mono

STOPWORDS = {
    "a", "an", "the", "i", "it", "to", "of", "and", "or", "uh", "um", "okay", "ok",
    "so", "we", "you", "is", "am", "are",
}
_TOKEN = re.compile(r"[a-z0-9']+")


def _frames(mono: np.ndarray, sr: int, win_sec: float = 0.04, hop_sec: float = 0.02):
    win = max(8, int(sr * win_sec))
    hop = max(4, int(sr * hop_sec))
    if mono.size < win:
        return
    window = np.hanning(win).astype(np.float32)
    for start in range(0, mono.size - win + 1, hop):
        yield mono[start:start + win] * window


def _f0(frame: np.ndarray, sr: int, fmin: float = 70.0, fmax: float = 400.0) -> float | None:
    x = frame - float(np.mean(frame))
    if float(np.sqrt(np.mean(x * x))) < 0.008:
        return None
    corr = np.correlate(x, x, mode="full")[len(x) - 1:]
    if corr[0] <= 1e-8:
        return None
    corr = corr / corr[0]
    lo = max(1, int(sr / fmax))
    hi = min(len(corr) - 1, int(sr / fmin))
    if hi <= lo + 1:
        return None
    k = lo + int(np.argmax(corr[lo:hi]))
    if 2 * k < hi and corr[2 * k] > 0.85 * corr[k]:
        k = 2 * k
    if corr[k] < 0.35:
        return None
    return float(sr / k)


def _spectrum(frame: np.ndarray, sr: int) -> tuple[float, float] | None:
    spec = np.abs(np.fft.rfft(frame))
    if spec.size < 4 or float(np.sum(spec)) <= 0:
        return None
    freqs = np.fft.rfftfreq(frame.size, 1.0 / sr)
    centroid = float(np.sum(freqs * spec) / (np.sum(spec) + 1e-12))
    low = float(np.sum(spec[freqs < 1000.0])) + 1e-8
    high = float(np.sum(spec[freqs >= 2000.0]))
    return centroid, high / low


def speaker_profile(wav: np.ndarray, sr: int) -> dict:
    mono = to_mono(wav) if np.asarray(wav).ndim > 1 else np.asarray(wav, dtype=np.float32)
    mono = np.asarray(mono, dtype=np.float32)
    bounds = speech_bounds(mono, sr)
    region = mono[bounds[0]:bounds[1]] if bounds else mono
    f0s, cents, tilts = [], [], []
    for frame in _frames(region, sr):
        f0 = _f0(frame, sr)
        if f0 is None:
            continue
        spec = _spectrum(frame, sr)
        f0s.append(f0)
        if spec is not None:
            cents.append(spec[0])
            tilts.append(spec[1])
    rms = float(np.sqrt(np.mean(np.square(region)))) if region.size else 0.0
    return {
        "f0": float(np.median(f0s)) if len(f0s) >= 3 else None,
        "centroid": float(np.median(cents)) if len(cents) >= 3 else None,
        "tilt": float(np.median(tilts)) if len(tilts) >= 3 else None,
        "rms": rms,
        "n_f0": len(f0s),
        "n_spec": len(cents),
    }


def _ratio_off(value: float | None, reference: float | None, lo: float, hi: float) -> bool | None:
    if value is None or reference is None or reference <= 0 or value <= 0:
        return None
    ratio = value / reference
    return ratio < lo or ratio > hi


def speaker_disagreements(candidate: dict, reference: dict, duration_sec: float) -> list[str]:
    """Return feature names that disagree. Empty when a feature cannot be measured."""
    use_f0 = duration_sec >= 0.45
    flags = []
    if use_f0:
        f0 = _ratio_off(candidate.get("f0"), reference.get("f0"), 0.75, 1.22)
        if f0 is True:
            flags.append("f0")
    centroid = _ratio_off(candidate.get("centroid"), reference.get("centroid"), 0.45, 1.22)
    if centroid is True:
        flags.append("centroid")
    return flags


def edge_issues(wav: np.ndarray, sr: int, rms_thr: float = 0.005) -> list[str]:
    mono = np.asarray(wav, dtype=np.float32)
    issues = []
    if mono.size == 0 or not np.isfinite(mono).all():
        return ["silent_or_empty"]
    if float(np.sqrt(np.mean(np.square(mono)))) < 1e-4:
        return ["silent_or_empty"]
    if int(np.sum(np.abs(mono) >= 0.999)) > 0:
        issues.append("clipping")
    bounds = speech_bounds(mono, sr, rms_thr)
    if bounds is None:
        issues.append("silent_or_empty")
        return issues
    first, last = bounds
    pre_n = int(sr * 0.01)
    onset = abs(float(mono[first])) if first < mono.size else 0.0
    if first < pre_n and onset > 0.05:
        issues.append("abrupt_onset")
    after_n = int(sr * 0.01)
    if last + after_n < mono.size:
        end_sample = abs(float(mono[last - 1])) if last else 0.0
        after = mono[last:last + after_n]
        if end_sample > 0.08 and after.size and float(np.max(np.abs(after))) < 0.004:
            issues.append("truncated_edge")
    return issues


def content_tokens(text: str) -> list[str]:
    words = _TOKEN.findall((text or "").lower())
    content = [w for w in words if w not in STOPWORDS]
    return content or words


def text_issues(expected: str, heard: str | None, language: str | None) -> list[str]:
    if heard is None:
        return []
    exp = content_tokens(expected)
    hyp = set(content_tokens(heard))
    if not exp:
        return []
    hit = sum(1 for word in exp if word in hyp)
    recall = hit / len(exp)
    issues = []
    lang = (language or "").lower()
    if lang and lang not in {"en", "english"} and recall < 0.5:
        issues.append("wrong_language")
    if len(exp) >= 3 and recall < 0.5:
        issues.append("missing_or_incorrect_text")
    elif len(exp) >= 2 and hit == 0 and len(hyp) > 0:
        issues.append("missing_or_incorrect_text")
    if len(exp) >= 2 and exp[-1] not in hyp and any(word in hyp for word in exp[:-1]):
        issues.append("truncated_speech")
    return issues


def assess_waveform(wav: np.ndarray, sr: int, reference: dict, *, min_speaker_features: int = 2) -> dict:
    mono = to_mono(wav) if np.asarray(wav).ndim > 1 else np.asarray(wav, dtype=np.float32)
    mono = np.asarray(mono, dtype=np.float32)
    duration = mono.size / float(sr) if sr else 0.0
    reasons = edge_issues(mono, sr)
    profile = speaker_profile(mono, sr)
    disagreed = speaker_disagreements(profile, reference, duration)
    # Pitch and brightness have to disagree together. Two brightness
    # measures are one phenomenon, and either one alone is not a rejection.
    del min_speaker_features
    if "f0" in disagreed and "centroid" in disagreed:
        reasons.append("wrong_speaker")
    return {
        "ok": not reasons,
        "reasons": reasons,
        "speaker_features_disagreed": disagreed,
        "speaker": {k: profile.get(k) for k in ("f0", "centroid", "tilt", "rms")},
        "duration_sec": duration,
    }


def assess_candidate(
    wav: np.ndarray,
    sr: int,
    text: str,
    reference: dict,
    *,
    asr_text: str | None = None,
    asr_language: str | None = None,
    asr_skipped: bool = False,
    min_speaker_features: int = 2,
) -> dict:
    result = assess_waveform(wav, sr, reference, min_speaker_features=min_speaker_features)
    extra = text_issues(text, asr_text, asr_language)
    reasons = list(result["reasons"])
    for item in extra:
        if item not in reasons:
            reasons.append(item)
    result["reasons"] = reasons
    result["ok"] = not reasons
    result["asr_text"] = asr_text
    result["asr_language"] = asr_language
    result["asr_skipped"] = asr_skipped
    return result
