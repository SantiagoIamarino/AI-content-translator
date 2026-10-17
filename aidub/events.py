"""Timed vocal events with explicit acoustic/text provenance and no noise passthrough.

Energy/harmonicity can nominate an uncertain region, never create dialogue.
Only source ASR or a microphone-hash-bound listening annotation can authorize a
speakable event. Annotation files are data, not instructions.
"""
from __future__ import annotations

import copy
import re
from pathlib import Path

import numpy as np
import soundfile as sf

from .config import resolve_path
from .util import fingerprint, read_json, sha256_file
from .fidelity import material_conflict, region_is_resolved

HESITATIONS_ES = {"eh", "em", "mmm", "mm", "hmm"}
REALIZATIONS = {"hesitation": {"Uh...", "Um...", "Hmm..."}}
NON_SPEECH = {"breath", "noise", "silence"}


def identity(cfg):
    opts = cfg.get("source_events") or {}
    if not opts.get("enabled"):
        return {}
    annotation = opts.get("annotations_file")
    return {"source_events": opts, "events_code": sha256_file(Path(__file__)),
            "source_fidelity_code": sha256_file(Path(__file__).with_name("fidelity.py")),
            "annotations_sha256": sha256_file(resolve_path(cfg, annotation)) if annotation else None}


def load_annotations(cfg, mic_sha, duration):
    path = (cfg.get("source_events") or {}).get("annotations_file")
    if not path:
        return []
    doc = read_json(resolve_path(cfg, path))
    if doc.get("schema") != "aidub.source_events.v1" or doc.get("mic_sha256") != mic_sha:
        raise ValueError("Source-event annotation schema/microphone hash mismatch")
    out, ids = [], set()
    for row in doc.get("events", []):
        e = copy.deepcopy(row)
        if not isinstance(e.get("id"), str) or e["id"] in ids:
            raise ValueError("Source-event IDs must be unique strings")
        ids.add(e["id"])
        start, end = float(e["start"]), float(e["end"])
        if not np.isfinite([start, end]).all() or not 0 <= start < end <= duration:
            raise ValueError("Source event outside microphone timeline")
        if e.get("kind") not in {"hesitation", "laugh", "sigh", "unknown"} | NON_SPEECH:
            raise ValueError("Unsupported source event kind")
        if e.get("status") not in {"confirmed", "uncertain"} or not str(e.get("evidence", "")).strip():
            raise ValueError("Source events require explicit status and evidence")
        if e["status"] == "confirmed" and e.get("provenance") != "user_listening":
            raise ValueError("Confirmed annotations require user_listening provenance")
        if e.get("realization") and e["realization"] not in REALIZATIONS.get(e["kind"], set()):
            raise ValueError("Unsupported event realization; annotations cannot insert arbitrary English")
        e.update(start=start, end=end, source="listening_annotation", timing="approximate")
        out.append(e)
    ordered = sorted(out, key=lambda e: e["start"])
    if any(a["end"] > b["start"] for a, b in zip(ordered, ordered[1:])):
        raise ValueError("Source-event annotations overlap")
    return ordered


def _tokens(text):
    return re.findall(r"\w+", text.lower())


def has_event_prefix(text, prefix):
    expected = re.findall(r"[a-z]+",prefix.lower())
    heard = re.findall(r"[a-z]+",(text or "").lower())
    return bool(expected and heard[:len(expected)] == expected)


def _words_for(seg, raw, offset):
    # Keep lexical evidence separate from broad energy-derived cue coverage.
    return [dict(w, start=float(w["start"])+offset, end=float(w["end"])+offset)
            for r in raw.get("segments", []) for w in r.get("words", [])
            if seg["start"]-.05 <= offset+(float(w["start"])+float(w["end"]))/2 <= seg["end"]+.05]


def _harmonic_candidate(audio, sr):
    """A conservative *nomination*, not a vowel/speech classifier."""
    x = np.asarray(audio).mean(axis=1) if audio.ndim > 1 else audio
    if len(x) < .25*sr:
        return None
    # At most a few seconds per suspect gap; no full-track arrays.
    x = x[::max(1, sr//8000)]; rate = sr/max(1, sr//8000)
    frame = round(.04*rate); scores = []
    for pos in range(0, len(x)-frame+1, frame):
        y = x[pos:pos+frame].astype(np.float64); y -= y.mean()
        rms = np.sqrt(np.mean(y*y))
        if rms < .003:
            scores.append(0.); continue
        ac = np.correlate(y, y, "full")[len(y)-1:]
        lo, hi = round(rate/350), min(len(ac), round(rate/65))
        scores.append(float(ac[lo:hi].max()/max(ac[0], 1e-12)))
    voiced = sum(v > .65 for v in scores)/max(1, len(scores))
    return {"periodic_frame_fraction": round(voiced, 3), "scope": "periodicity; not proof of speech"} if voiced >= .7 else None


def apply_events(built, raw, mic_path, offset, cfg, mic_sha):
    """Return immutable event accounting plus speakable cues for supported events.

    Silence/noise/breath never becomes text. Confirmed events conflicting with
    recognized words remain unresolved rather than deleting or duplicating words.
    """
    opts = cfg.get("source_events") or {}
    if not opts.get("enabled"):
        return built
    out = copy.deepcopy(built); segments = out["segments"]
    next_id = max((s["id"] for s in segments), default=0)+1
    with sf.SoundFile(mic_path) as handle:
        sr = handle.samplerate
        def read(a, b):
            lo = max(0, round((a-offset)*sr)); hi = min(handle.frames, round((b-offset)*sr))
            handle.seek(lo)
            return handle.read(max(0, hi-lo), dtype="float32", always_2d=True)
        events = load_annotations(cfg, mic_sha, offset+handle.frames/sr)
        for s in segments:
            s["source_words"] = _words_for(s, raw, offset)
            conflict = material_conflict(s)
            if conflict:
                s["material_source_conflict"] = conflict
            if set(_tokens(s["spanish"])) <= HESITATIONS_ES and _tokens(s["spanish"]):
                # Already-transcribed isolated hesitations need no second cue.
                e = dict(id=f"asr-{s['id']}", start=s["start"], end=s["end"], kind="hesitation",
                         status="confirmed", source="source_asr", evidence=s["spanish"],
                         realization="Uh...", cue_id=s["id"], disposition="translated_with_cue")
                s["vocal_events"] = [e]; events.append(e)
        for e in events:
            if e.get("cue_id"):
                continue
            e["disposition"] = "unresolved"
            if e["status"] != "confirmed":
                continue
            if e["kind"] in NON_SPEECH:
                e["disposition"] = "intentionally_not_voiced"; continue
            if e["kind"] not in REALIZATIONS:
                e["reason"] = "No validated synthesis or passthrough for this event"; continue
            overlaps = [s for s in segments if s["start"] < e["end"] and s["end"] > e["start"]]
            if any(w["end"] > e["start"]+.01 and w["start"] < e["end"]-.01
                   for s in overlaps for w in s.get("source_words", [])):
                e["reason"] = "Event conflicts with recognized words; requires boundary reconciliation"; continue
            if len(overlaps) > 1:
                e["reason"] = "Event crosses cue boundaries"; continue
            if overlaps:
                s = overlaps[0]; words = s.get("source_words", [])
                # Validate reconstruction before splitting a cue inside its span.
                if not words or _tokens(" ".join(w["word"] for w in words)) != _tokens(s["spanish"]):
                    e["reason"] = "Cannot reconcile cue words without changing transcript"; continue
                before = [w for w in words if w["end"] <= e["start"]+.01]
                after = [w for w in words if w["start"] >= e["end"]-.01]
                if after and not before and opts.get("realization_mode") == "prefix_with_following":
                    # A held filler and its continuation are one performance.
                    # The internal lexical onset is approximate, not a hard
                    # synthesis deadline for the filler alone.
                    e.update(cue_id=s["id"],disposition="translated_with_cue",realization_mode="prefix",
                             lexical_onset_estimate=after[0]["start"])
                    s.update(start=e["start"],spanish="Eh... "+s["spanish"],
                             required_event_prefix=e.get("realization","Uh..."),vocal_events=[copy.deepcopy(e)])
                    continue
                if before and after:
                    tail = copy.deepcopy(s); tail.update(id=next_id, start=e["end"],
                            spanish=" ".join(w["word"].strip() for w in after), source_words=after)
                    next_id += 1; segments.append(tail)
                    s.update(end=e["start"], spanish=" ".join(w["word"].strip() for w in before), source_words=before)
                elif after:
                    s["start"] = e["end"]
                elif before:
                    s["end"] = e["start"]
                else:
                    e["reason"] = "No lexical words remain after event separation"; continue
            e.update(cue_id=next_id, disposition="translated_with_cue")
            segments.append(dict(id=next_id, start=e["start"], end=e["end"], spanish="Eh...",
                                 english=None, english_original=None, revisions=[], notes=e["evidence"],
                                 anchor_type="vocal_event", uncertain_words=[], vocal_events=[copy.deepcopy(e)],
                                 fixed_event_realization=e.get("realization", "Uh..."), source_words=[]))
            next_id += 1
        # Leading/internal holes are checked even when broad cue coverage hides
        # them. Periodicity nominates UNKNOWN; it never authorizes a word.
        for s in segments:
            words = s.get("source_words", [])
            holes = [(s["start"], words[0]["start"])] if words else []
            holes += [(a["end"], b["start"]) for a, b in zip(words, words[1:])]
            for a, b in holes:
                if b-a < .25 or b-a > 3 or any(e["start"] < b and e["end"] > a for e in events):
                    continue
                evidence = _harmonic_candidate(read(a, b), sr)
                if evidence:
                    events.append(dict(id="candidate-"+fingerprint([a,b])[:12], start=a, end=b,
                                       kind="unknown", status="uncertain", source="periodicity_nomination",
                                       evidence=evidence, disposition="unresolved"))
    out["segments"] = sorted(segments, key=lambda s: (s["start"], s["id"]))
    out["vocal_events"] = {"schema": "aidub.source_events.v1", "mic_sha256": mic_sha,
                           "events": sorted(events, key=lambda e: e["start"]),
                           "passthrough": False, "note": "No acoustic nomination is automatically voiced."}
    return out


def event_placement_report(ledger, rows, region_resolutions=None):
    by_id = {s["id"]: s for s in rows}
    events = copy.deepcopy(ledger.get("events", []))
    for e in events:
        region = {"kind": "event", "span": [e["start"],e["end"]], "original": copy.deepcopy(e)}
        if region_is_resolved(region, region_resolutions, ledger.get("mic_sha256")):
            e["original_disposition"] = e.get("disposition")
            e["disposition"] = "intentionally_not_voiced"
            e["resolution"] = "evidence_bound_near_silence"
        row = by_id.get(e.get("cue_id"))
        if row:
            e.update(english=row.get("english"), placed=bool(row.get("placed")),
                     placement_start=row.get("placement_start"), placement_end=row.get("placement_end"))
            if e.get("realization_mode") == "prefix":
                e["prefix_verified"] = bool(row.get("quality",{}).get("event_prefix_verified"))
        e["accounted"] = e.get("disposition") == "intentionally_not_voiced" or bool(
            e.get("status") == "confirmed" and row and row.get("placed") and
            (e.get("realization_mode") != "prefix" or e.get("prefix_verified")))
    return {"schema": "aidub.event_placement.v1", "events": events,
            "unresolved": [e["id"] for e in events if not e["accounted"]]}
