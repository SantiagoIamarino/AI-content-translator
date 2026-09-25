import numpy as np

from .audio import voiced_mask


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    runs = []
    start = None
    for i, voiced in enumerate(mask):
        if voiced and start is None:
            start = i
        elif not voiced and start is not None:
            runs.append((start, i))
            start = None
    if start is not None:
        runs.append((start, len(mask)))
    return runs


_HALLUCINATIONS = ("gracias por ver", "thanks for watching", "subtítulos", "subtitles by")


def review_low_energy(text: str, region: np.ndarray, sr: int, rms_thr: float) -> tuple[bool, str]:
    """Second look at a line the fixed RMS gate would drop.

    Near-silence and noise-like slices stay dropped, including the usual
    end-of-video hallucination. A quiet harmonic slice is kept.
    """
    mono = np.asarray(region, dtype=np.float32)
    if mono.ndim > 1:
        mono = mono.mean(axis=1)
    lowered = (text or "").lower()
    if any(phrase in lowered for phrase in _HALLUCINATIONS):
        return False, "hallucination_phrase"
    if mono.size == 0 or sr <= 0:
        return False, "near_silence"
    rms = float(np.sqrt(np.mean(mono * mono)))
    if rms < float(rms_thr) * 0.25:
        return False, "near_silence"
    window = np.hanning(mono.size).astype(np.float32)
    spec = np.abs(np.fft.rfft(mono * window))[1:]
    if spec.size == 0:
        return False, "near_silence"
    geometric = float(np.exp(np.mean(np.log(spec + 1e-12))))
    arithmetic = float(np.mean(spec)) + 1e-12
    flatness = geometric / arithmetic
    if flatness > 0.4:
        return False, "noise_like"
    if flatness < 0.25:
        return True, "borderline_harmonic"
    return False, "below_threshold"


def _join_words(words: list[dict]) -> str:
    parts = []
    for word in words:
        token = str(word.get("word", "")).strip()
        if token:
            parts.append(token)
    return " ".join(parts)


def build_segments(whisper: dict, wav: np.ndarray, sr: int, cfg: dict, offset_sec: float = 0.0) -> dict:
    mask = voiced_mask(wav, sr, float(cfg["energy_rms"]), float(cfg["energy_window_sec"]))
    lookback = int(round(float(cfg["onset_lookback_sec"]) * sr))
    tail = int(round(float(cfg["end_tail_sec"]) * sr))
    min_voiced = int(round(float(cfg["min_voiced_sec"]) * sr))
    merge_silence = int(round(float(cfg["merge_max_silence_sec"]) * sr))
    uncertain_p = float(cfg["uncertain_probability"])
    dropped = []
    uncertain = []
    merges = []
    candidates = []
    prev_end = 0
    for raw in whisper.get("segments") or []:
        words = raw.get("words") or []
        text = _join_words(words) if words else str(raw.get("text") or "").strip()
        if not text:
            dropped.append({"text": "", "reason": "empty", "whisper_span": [raw.get("start"), raw.get("end")]})
            continue
        ws = int(round(float(raw["start"]) * sr))
        we = int(round(float(raw["end"]) * sr))
        region_start = max(prev_end, ws - lookback, 0)
        region_end = min(len(mask), max(we, ws) + tail)
        region = mask[region_start:region_end]
        voiced_count = int(np.count_nonzero(region))
        borderline = None
        if voiced_count < min_voiced:
            slice_wav = wav[max(0, ws):min(len(mask), max(we, ws + 1))]
            keep, why = review_low_energy(text, slice_wav, sr, float(cfg["energy_rms"]))
            if not keep:
                dropped.append({
                    "text": text,
                    "reason": "no_energy",
                    "review": why,
                    "whisper_span": [float(raw["start"]), float(raw["end"])],
                })
                continue
            borderline = why
            start = ws
            end = max(we, ws + 1)
        else:
            rel = np.flatnonzero(region)
            start = region_start + int(rel[0])
            end = region_start + int(rel[-1]) + 1
            if end <= start:
                dropped.append({"text": text, "reason": "no_energy", "review": "empty_span", "whisper_span": [float(raw["start"]), float(raw["end"])]})
                continue
        low = []
        for word in words:
            prob = word.get("probability")
            if prob is not None and float(prob) < uncertain_p:
                low.append({"word": str(word.get("word", "")).strip(), "probability": float(prob), "start": word.get("start"), "end": word.get("end")})
        candidates.append({
            "text": text,
            "start_sample": start,
            "end_sample": end,
            "whisper_start": float(raw["start"]),
            "whisper_end": float(raw["end"]),
            "uncertain_words": low,
            "merged_from": [text],
            "borderline": borderline,
        })
        prev_end = end
        uncertain.extend(low)

    merged = []
    for cand in candidates:
        if not merged:
            merged.append(cand)
            continue
        gap_start = merged[-1]["end_sample"]
        gap_end = cand["start_sample"]
        gap = mask[gap_start:gap_end]
        silence = int(gap.size - np.count_nonzero(gap)) if gap.size else 0
        if gap_end >= gap_start and silence <= merge_silence:
            merges.append({
                "kept": merged[-1]["text"],
                "merged": cand["text"],
                "reason": f"silence between energy spans <= {cfg['merge_max_silence_sec']}s",
            })
            merged[-1]["text"] = f"{merged[-1]['text']} {cand['text']}".strip()
            merged[-1]["end_sample"] = cand["end_sample"]
            merged[-1]["whisper_end"] = cand["whisper_end"]
            merged[-1]["uncertain_words"].extend(cand["uncertain_words"])
            merged[-1]["merged_from"].extend(cand["merged_from"])
        else:
            merged.append(cand)

    segments = []
    for index, cand in enumerate(merged, start=1):
        start = cand["start_sample"] / sr + offset_sec
        end = cand["end_sample"] / sr + offset_sec
        dur = end - start
        n_words = len(cand["text"].split())
        anchor = "reaction" if n_words <= 3 and dur < 1.6 else "utterance"
        notes = []
        if abs(start - (cand["whisper_start"] + offset_sec)) > 0.05:
            notes.append(
                f"Whisper start {cand['whisper_start'] + offset_sec:.3f}; energy onset {start:.3f}. "
                "Timestamps are approximate, not forced alignment."
            )
        if cand["uncertain_words"]:
            shown = ", ".join(f"{w['word']} p={w['probability']:.3f}" for w in cand["uncertain_words"])
            notes.append(f"Uncertain words: {shown}. Not rewritten.")
        if len(cand["merged_from"]) > 1:
            notes.append("Merged Whisper segments on a short energy gap: " + " | ".join(cand["merged_from"]))
        if cand.get("borderline"):
            notes.append(
                f"Kept after energy review ({cand['borderline']}). "
                f"The fixed RMS gate was {cfg['energy_rms']}, and the slice was speech-like rather than silence."
            )
        segments.append({
            "id": index,
            "start": round(start, 6),
            "end": round(end, 6),
            "spanish": cand["text"],
            "english": None,
            "english_original": None,
            "anchor_type": anchor,
            "anchor_type_note": "heuristic from word count and duration, not a linguistic label",
            "notes": " ".join(notes),
            "whisper_start": cand["whisper_start"] + offset_sec,
            "whisper_end": cand["whisper_end"] + offset_sec,
            "uncertain_words": cand["uncertain_words"],
            "revisions": [],
        })

    covered = np.zeros(len(mask), dtype=bool)
    for cand in merged:
        covered[cand["start_sample"]:cand["end_sample"]] = True
    untranscribed = []
    for run_start, run_end in _runs(mask):
        if int(np.count_nonzero(~covered[run_start:run_end])) >= min_voiced and int(np.count_nonzero(mask[run_start:run_end] & ~covered[run_start:run_end])) >= min_voiced:
            untranscribed.append({
                "span": [round(run_start / sr + offset_sec, 6), round(run_end / sr + offset_sec, 6)],
                "reason": "Voiced energy with no kept Whisper text. Not invented as dialogue.",
            })
    return {
        "timestamp_status": "whisper_segments_plus_energy_onset_approximate_not_forced_alignment",
        "segments": segments,
        "dropped": dropped,
        "merges": merges,
        "uncertain": uncertain,
        "untranscribed_energy": untranscribed,
        "corrections": [
            {"kind": "drop", **item} for item in dropped
        ] + [
            {"kind": "merge", **item} for item in merges
        ],
    }
