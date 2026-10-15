"""Second, independent ASR hearing for uncertain cues, suspected duplicates and voiced gaps.

Energy is not treated as proof of speech. A voiced gap becomes a new cue only
when the second hearing produces confident words inside that gap. Otherwise the
gap is classified and reported, never filled by guessing.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import numpy as np
import soundfile as sf

from .segment import _HALLUCINATIONS, coverage_gaps_file
from .textnorm import strip_accents
from .util import fingerprint, read_json, write_json

DEFAULTS = {
    "pad_sec": 0.35,
    "accept_probability": 0.6,
    "min_word_probability": 0.3,
    "merge_gap_sec": 0.3,
    "max_no_speech_prob": 0.6,
    "duplicate_min_tokens": 2,
    "options": {"condition_on_previous_text": False, "beam_size": 5, "best_of": 5},
}


def settings(cfg: dict) -> dict:
    block = cfg.get("asr_second_pass") or {}
    if not block.get("enabled"):
        return {}
    merged = dict(DEFAULTS)
    merged.update({k: v for k, v in block.items() if k != "options"})
    merged["options"] = dict(DEFAULTS["options"], **(block.get("options") or {}))
    return merged


def es_tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9ñ]+", strip_accents((text or "").lower()).replace("ñ", "n"))


def es_tokens_exact(text: str) -> list[str]:
    """Lowercase words with accents kept: si/sí, el/él and que/qué differ in meaning."""
    return re.findall(r"[a-z0-9ñáéíóúü]+", (text or "").lower())


def _find(haystack: list[str], needle: list[str]) -> list[int]:
    hits, k = [], 0
    while needle and k <= len(haystack) - len(needle):
        if haystack[k:k + len(needle)] == needle:
            hits.append(k)
            k += len(needle)
        else:
            k += 1
    return hits


def flatness(region: np.ndarray) -> float:
    if region.size < 64:
        return 1.0
    spec = np.abs(np.fft.rfft(region * np.hanning(region.size)))[1:] + 1e-12
    return float(np.exp(np.mean(np.log(spec))) / np.mean(spec))


def duplicate_pairs(segments: list[dict], min_tokens: int) -> list[tuple[int, int, str]]:
    """Adjacent cues where the later text repeats the earlier text or its tail."""
    pairs = []
    for i in range(len(segments) - 1):
        a, b = es_tokens(segments[i]["spanish"]), es_tokens(segments[i + 1]["spanish"])
        if len(b) < min_tokens:
            continue
        if a == b:
            pairs.append((i, i + 1, "identical"))
        elif len(a) > len(b) and a[-len(b):] == b:
            pairs.append((i, i + 1, "tail_repeat"))
        elif len(b) > len(a) >= min_tokens and b[:len(a)] == a:
            pairs.append((i, i + 1, "head_repeat"))
    return pairs


class _Mic:
    def __init__(self, path: Path, offset_sec: float):
        self.handle = sf.SoundFile(path)
        self.sr = self.handle.samplerate
        self.offset = float(offset_sec)

    def read(self, start_sec: float, end_sec: float) -> np.ndarray:
        lo = max(0, int(round((start_sec - self.offset) * self.sr)))
        hi = min(self.handle.frames, int(round((end_sec - self.offset) * self.sr)))
        if hi <= lo:
            return np.zeros((0, self.handle.channels), dtype=np.float32)
        self.handle.seek(lo)
        return self.handle.read(hi - lo, dtype="float32", always_2d=True)

    def close(self):
        self.handle.close()


def _words(result: dict, window_start: float) -> list[dict]:
    words = []
    for seg in result.get("segments") or []:
        for w in seg.get("words") or []:
            words.append({"word": str(w.get("word", "")).strip(), "start": window_start + float(w["start"]),
                          "end": window_start + float(w["end"]), "probability": float(w.get("probability") or 0.0),
                          "no_speech_prob": float(seg.get("no_speech_prob") or 0.0)})
    return [w for w in words if w["word"]]


def _inside(words: list[dict], lo: float, hi: float) -> list[dict]:
    return [w for w in words if lo <= (w["start"] + w["end"]) / 2 <= hi]


def _summary(words: list[dict]) -> dict:
    if not words:
        return {"text": "", "mean_probability": None, "min_probability": None}
    probs = [w["probability"] for w in words]
    return {"text": " ".join(w["word"] for w in words).strip(), "mean_probability": round(float(np.mean(probs)), 4),
            "min_probability": round(float(np.min(probs)), 4),
            "max_no_speech_prob": round(max(w["no_speech_prob"] for w in words), 4)}


def run_second_pass(job_dir: Path, built: dict, mic_path: Path, offset_sec: float, cfg: dict, transcribe,
                    mic_sha: str = "") -> dict:
    """transcribe(path, options) -> Whisper full result with word timestamps."""
    opts = settings(cfg)
    segments = sorted((dict(s) for s in built["segments"]), key=lambda s: (float(s["start"]), int(s["id"])))
    pad = float(opts["pad_sec"])
    # Interpretation policy must not invalidate identical cached hearings.
    hearing_settings = {k:v for k,v in opts.items() if k != "confirm_recovered"}
    identity = fingerprint({"mic": mic_sha or str(mic_path), "settings": hearing_settings, "version": 1,
                            "model": cfg.get("asr_second_pass", {}).get("model"),
                            "segments": [(s["id"], s["start"], s["end"], s["spanish"]) for s in segments],
                            "gaps": built.get("untranscribed_energy")})
    work = job_dir / "transcribe" / "second_pass" / identity[:16]
    work.mkdir(parents=True, exist_ok=True)
    mic = _Mic(mic_path, offset_sec)
    audit = {"schema": "aidub.second_pass.v1", "identity": identity, "settings": opts, "targets": []}

    def hear(kind: str, key: str, lo: float, hi: float) -> tuple[list[dict], float]:
        lo, hi = max(0.0, lo), max(lo + 0.05, hi)
        result_path = work / f"{kind}_{key}.json"
        saved = read_json(result_path) if result_path.is_file() else {}
        if saved.get("window") == [lo, hi]:
            return saved["words"], lo
        audio = mic.read(lo, hi)
        wav = work / f"{kind}_{key}.wav"
        tmp = wav.with_name(wav.stem + f".{os.getpid()}.tmp.wav")
        sf.write(tmp, audio, mic.sr, subtype="PCM_16")
        os.replace(tmp, wav)
        result = transcribe(str(wav), opts["options"])
        words = _words(result, lo)
        write_json(result_path, {"window": [lo, hi], "words": words, "text": result.get("text", "")})
        return words, lo

    try:
        drop: set[int] = set()
        for i, j, why in duplicate_pairs(segments, int(opts["duplicate_min_tokens"])):
            a, b = segments[i], segments[j]
            if i in drop or j in drop:
                continue
            lo, hi = float(a["start"]) - pad, float(b["end"]) + pad
            words, _ = hear("dup", f"{a['id']}_{b['id']}", lo, hi)
            heard = es_tokens(" ".join(w["word"] for w in words))
            phrase = es_tokens(b["spanish"]) if why != "head_repeat" else es_tokens(a["spanish"])
            hits = _find(heard, phrase)
            target = {"kind": "duplicate", "ids": [a["id"], b["id"]], "pattern": why, "window": [lo, hi],
                      "phrase": " ".join(phrase), "occurrences": len(hits), **_summary(words)}
            if len(hits) >= 2:
                target["outcome"] = "confirmed_repetition"
            elif len(hits) == 1:
                k = hits[0]
                flat = [w for w in words if es_tokens(w["word"])]
                occ = flat[k:k + len(phrase)] if k + len(phrase) <= len(flat) else flat[k:]
                t0 = occ[0]["start"] if occ else float(b["start"])
                t1 = occ[-1]["end"] if occ else float(b["end"])
                overlap_b = max(0.0, min(t1, float(b["end"])) - max(t0, float(b["start"])))
                overlap_a = max(0.0, min(t1, float(a["end"])) - max(t0, float(a["start"])))
                if why == "identical":
                    loser = j if overlap_a >= overlap_b else i
                    drop.add(loser)
                    target["outcome"] = f"dropped_duplicate_cue_{segments[loser]['id']}"
                elif why == "tail_repeat" and overlap_b > overlap_a:
                    words_a = a["spanish"].split()
                    a["spanish"] = " ".join(words_a[:max(1, len(words_a) - len(b["spanish"].split()))])
                    a["notes"] = " ".join(x for x in (a.get("notes"), "Second ASR pass heard the trailing phrase once, in the next cue; removed the duplicate from this cue.") if x)
                    target["outcome"] = f"trimmed_duplicate_tail_from_{a['id']}"
                elif why == "head_repeat":
                    # B contains unique suffix words. Hearing the common prefix
                    # once is never evidence for deleting those words (candado).
                    full = es_tokens(b["spanish"])
                    if _find(heard, full) and overlap_b > overlap_a:
                        drop.add(i)
                        target["outcome"] = f"dropped_duplicate_cue_{a['id']}"
                    else:
                        target["outcome"] = "unresolved_duplicate_unique_words_preserved"
                else:
                    drop.add(j)
                    target["outcome"] = f"dropped_duplicate_cue_{b['id']}"
                target["occurrence_span"] = [t0, t1]
            else:
                target["outcome"] = "unresolved_duplicate"
                for seg in (a, b):
                    seg["notes"] = " ".join(x for x in (seg.get("notes"), "Possible ASR duplicate with the neighboring cue; the second hearing could not resolve it.") if x)
            audit["targets"].append(target)

        kept = [s for k, s in enumerate(segments) if k not in drop]
        dropped_dup = [dict(s, reason="second_pass_duplicate") for k, s in enumerate(segments) if k in drop]

        for k, seg in enumerate(kept):
            if not seg.get("uncertain_words") and not seg.get("borderline"):
                continue
            prev_end = float(kept[k - 1]["end"]) if k else 0.0
            next_start = float(kept[k + 1]["start"]) if k + 1 < len(kept) else float(seg["end"]) + pad
            lo = max(prev_end, float(seg["start"]) - pad)
            hi = min(next_start, float(seg["end"]) + pad)
            words, _ = hear("cue", str(seg["id"]), lo, hi)
            inside = _inside(words, float(seg["start"]) - 0.15, float(seg["end"]) + 0.15)
            info = _summary(inside)
            target = {"kind": "uncertain_cue", "id": seg["id"], "window": [lo, hi], "first_pass": seg["spanish"], **info}
            if not inside:
                target["outcome"] = "second_pass_heard_nothing"
                seg["notes"] = " ".join(x for x in (seg.get("notes"), "Second ASR pass heard no words here; first-pass text kept.") if x)
            elif es_tokens_exact(info["text"]) == es_tokens_exact(seg["spanish"]):
                target["outcome"] = "confirmed"
            else:
                target["outcome"] = "alternative_reading"
                seg.setdefault("asr_alternatives", []).append({
                    "text": info["text"], "mean_probability": info["mean_probability"],
                    "source": "second_pass", "note": "Independent second hearing; first-pass text is kept as spanish."})
            audit["targets"].append(target)

        if cfg.get("segmentation"):
            gaps = coverage_gaps_file(mic_path, kept, cfg["segmentation"], offset_sec=offset_sec,
                                      index_path=job_dir / "transcribe" / "energy" / f"surviving_{mic_sha or identity}.sqlite")
        else:
            gaps = list(built.get("untranscribed_energy") or [])
        gaps = _merge_gaps(gaps, float(opts["merge_gap_sec"]))
        recovered = []
        cue_spans = [(float(s["start"]), float(s["end"])) for s in kept]
        for n, gap in enumerate(gaps):
            uncovered = _subtract(gap["span"], cue_spans)
            if sum(b - a for a, b in uncovered) < 0.03:
                gap["second_pass"] = {"outcome": "covered_by_existing_cue", "uncovered_sec": 0.0}
                audit["targets"].append({"kind": "voiced_gap", "span": gap["span"], **gap["second_pass"]})
                continue
            g0, g1 = uncovered[0][0], uncovered[-1][1]
            before = [e for s, e in cue_spans if e <= g0 + 1e-3]
            after = [s for s, e in cue_spans if s >= g1 - 1e-3]
            lo = max(max(before) if before else 0.0, g0 - pad)
            hi = min(min(after) if after else g1 + pad, g1 + pad)
            words, _ = hear("gap", f"{n:04d}", lo, hi)
            inside = [w for w in words
                      if any(a - 0.1 <= (w["start"] + w["end"]) / 2 <= b + 0.1 for a, b in uncovered)
                      and not any(s <= (w["start"] + w["end"]) / 2 <= e for s, e in cue_spans)]
            info = _summary(inside)
            region = mic.read(g0, g1)
            mono = region.mean(axis=1) if region.ndim > 1 and region.size else region.reshape(-1)
            flat = flatness(mono)
            lowered = info["text"].lower()
            neighbor_text = " ".join(s["spanish"] for s in kept
                                     if abs(float(s["end"]) - g0) < 1.0 or abs(float(s["start"]) - g1) < 1.0)
            repeats_neighbor = bool(inside) and _contained(es_tokens(info["text"]), es_tokens(neighbor_text))
            if repeats_neighbor and any(s.get("source_words") for s in kept):
                # Matching a token somewhere in a long neighboring cue does
                # not establish that this *timed* reaction is already covered.
                nearby = " ".join(w["word"] for s in kept for w in s.get("source_words",[])
                                  if float(w["end"]) >= g0-.25 and float(w["start"]) <= g1+.25)
                repeats_neighbor = _contained(es_tokens(info["text"]),es_tokens(nearby))
            confident = (inside and info["mean_probability"] >= float(opts["accept_probability"])
                         and info["min_probability"] >= float(opts["min_word_probability"])
                         and info["max_no_speech_prob"] <= float(opts["max_no_speech_prob"])
                         and any(len(t) >= 2 for t in es_tokens(info["text"]))
                         and not any(p in lowered for p in _HALLUCINATIONS))
            confirmation = None
            if confident and not repeats_neighbor and opts.get("confirm_recovered"):
                # Tiny isolated windows can confidently hallucinate a familiar
                # sign-off (the 20-ms "Gracias" reading in the repetition test).
                # Require a matching *timed* reading with neighboring context,
                # without supplying an expected-text prompt.
                ca = max(0.,g0-max(.8,pad))
                cb = min(offset_sec+mic.handle.frames/mic.sr,g1+max(.8,pad))
                context_words,_ = hear("gap_confirm",f"{n:04d}",ca,cb)
                # Whisper can assign a quiet word a broad interval beginning
                # well before its acoustic onset (the saved "Intentar..."
                # hearing). Require meaningful overlap, not an exact midpoint.
                timed = [w for w in context_words if any(
                    max(0.,min(w["end"],b)-max(w["start"],a)) >= min(.06,(b-a)/2)
                    for a,b in uncovered)]
                corroborated = _summary(timed)
                matches = bool(_find(es_tokens(corroborated["text"]),es_tokens(info["text"])))
                confirmed = bool(matches and corroborated["mean_probability"] >= float(opts["accept_probability"])
                                 and corroborated["min_probability"] >= float(opts["min_word_probability"]))
                confirmation = dict(window=[ca,cb],**corroborated,confirmed=confirmed,
                                    scope="same recognizer with neighboring acoustic context; no expected-text prompt")
                confident = confident and confirmed
            if repeats_neighbor:
                outcome = "already_transcribed"
            elif confident:
                outcome = "recovered"
                start = max(lo, min(g0, inside[0]["start"]))
                end = min(hi, max(g1, inside[-1]["end"]))
                recovered.append({
                    "id": -1, "start": round(start, 6), "end": round(end, 6), "spanish": info["text"],
                    "english": None, "english_original": None, "anchor_type": "reaction" if len(inside) <= 3 and end - start < 1.6 else "utterance",
                    "anchor_type_note": "heuristic from word count and duration, not a linguistic label",
                    "notes": f"Recovered by second ASR pass from voiced energy without first-pass text (mean p={info['mean_probability']}).",
                    "whisper_start": inside[0]["start"], "whisper_end": inside[-1]["end"],
                    "uncertain_words": [w for w in inside if w["probability"] < 0.5], "revisions": [],
                    "recovered": True})
            elif inside:
                outcome = "unintelligible"
            else:
                outcome = "no_speech_heard" if flat < 0.4 else "non_speech_energy"
            gap["second_pass"] = {"outcome": outcome, "window": [lo, hi], "flatness": round(flat, 4),
                                  "uncovered": [[round(a, 4), round(b, 4)] for a, b in uncovered], **info}
            if confirmation is not None:
                gap["second_pass"]["context_confirmation"] = confirmation
            audit["targets"].append({"kind": "voiced_gap", "span": gap["span"], "outcome": outcome, **gap["second_pass"]})
    finally:
        mic.close()

    merged_segments = sorted(kept + recovered, key=lambda s: float(s["start"]))
    for index, seg in enumerate(merged_segments, start=1):
        seg["id"] = index
    audit["dropped_duplicates"] = dropped_dup
    audit["recovered"] = len(recovered)
    built = dict(built)
    built["segments"] = merged_segments
    built["untranscribed_energy"] = gaps
    built["source_coverage"] = {"basis": "surviving_cues_after_second_pass", "kept": len(merged_segments),
                                "removed_duplicates": len(dropped_dup),
                                "uncovered": [part for gap in gaps for part in _subtract(
                                    gap["span"], [(s["start"], s["end"]) for s in merged_segments])]}
    built["corrections"] = list(built.get("corrections") or []) + [
        {"kind": "second_pass_duplicate", "text": s["spanish"], "span": [s["start"], s["end"]]} for s in dropped_dup
    ] + [{"kind": "second_pass_recovered", "text": s["spanish"], "span": [s["start"], s["end"]]} for s in recovered]
    write_json(job_dir / "transcribe" / "second_pass.json", audit)
    return built


def _subtract(span: list[float], covered: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Parts of an energy run that no kept cue covers."""
    parts = [(float(span[0]), float(span[1]))]
    for c0, c1 in covered:
        nxt = []
        for a, b in parts:
            if c1 <= a or c0 >= b:
                nxt.append((a, b))
                continue
            if c0 > a:
                nxt.append((a, c0))
            if c1 < b:
                nxt.append((c1, b))
        parts = nxt
    return [(a, b) for a, b in parts if b - a > 1e-4]


def final_coverage(built):
    """Coverage after joining and event realization; energy spans are not speech."""
    spans=[(float(s["start"]),float(s["end"])) for s in built["segments"]]
    parts=[p for g in built.get("untranscribed_energy",[]) for p in _subtract(g["span"],spans)]
    return {"basis":"surviving_final_cues_including_events","kept":len(spans),"uncovered":parts,
            "uncovered_span_sec":sum(b-a for a,b in parts),
            "scope":"uncovered reported energy spans, possibly including quiet bridges; not proven speech"}


def _contained(needle: list[str], haystack: list[str]) -> bool:
    return bool(needle) and bool(_find(haystack, needle))


def _merge_gaps(gaps: list[dict], merge_gap: float) -> list[dict]:
    merged = []
    for gap in sorted(gaps, key=lambda g: g["span"][0]):
        if merged and gap["span"][0] - merged[-1]["span"][1] <= merge_gap:
            merged[-1]["span"][1] = max(merged[-1]["span"][1], gap["span"][1])
            merged[-1]["merged"] = merged[-1].get("merged", 1) + 1
        else:
            merged.append({"span": list(gap["span"]), "reason": gap.get("reason")})
    return merged


REVIEWED_OUTCOMES = {"recovered", "unintelligible", "no_speech_heard", "non_speech_energy",
                     "covered_by_existing_cue", "already_transcribed"}


def unreviewed_gaps(gaps: list[dict]) -> list[dict]:
    return [g for g in gaps if (g.get("second_pass") or {}).get("outcome") not in REVIEWED_OUTCOMES]
