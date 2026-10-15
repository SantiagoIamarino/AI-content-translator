"""Source-supported pause evidence and contextual candidate evaluation.

Raw text/waveform verification remains cached independently. This module only
evaluates whether a take's pauses match this source cue; it cannot authorize
missing words or repair a failed speaker/content check.
"""
from __future__ import annotations

import copy
from pathlib import Path

import numpy as np
import soundfile as sf

from .audio import speech_bounds, to_mono
from .util import sha256_file


def identity(cfg):
    opts = (cfg.get("voice_selection") or {}).get("source_pauses") or {}
    return {"source_pauses": opts, "performance_code": sha256_file(Path(__file__))} if opts.get("enabled") else {}


def quiet_intervals(wav, sr, threshold=.005, minimum=.25):
    x = to_mono(wav) if np.asarray(wav).ndim > 1 else np.asarray(wav)
    bounds = speech_bounds(x, sr, threshold)
    if bounds is None:
        return []
    lo, hi = bounds; win = max(1, round(.02*sr))
    n = (hi-lo)//win
    if not n:
        return []
    quiet = np.sqrt(np.mean(x[lo:lo+n*win].reshape(n,win).astype(np.float64)**2,axis=1)) <= threshold
    edges = np.flatnonzero(np.diff(np.r_[False,quiet,False].astype(np.int8)))
    return [{"start": (lo+a*win)/sr, "end": (lo+b*win)/sr, "duration": (b-a)*win/sr}
            for a,b in zip(edges[::2],edges[1::2]) if (b-a)*win/sr >= minimum]


def attach_source_pauses(built, mic, offset, cfg):
    if not identity(cfg):
        return built
    out = copy.deepcopy(built)
    with sf.SoundFile(mic) as f:
        for s in out["segments"]:
            lo = max(0, round((s["start"]-offset)*f.samplerate))
            hi = min(f.frames, round((s["end"]-offset)*f.samplerate))
            f.seek(lo); x = f.read(max(0,hi-lo),dtype="float32",always_2d=True)
            s["source_pauses"] = [dict(p,start=p["start"]+s["start"],end=p["end"]+s["start"],
                                        evidence="mic low-energy interval; approximate, not forced alignment")
                                    for p in quiet_intervals(x,f.samplerate)]
    return out


def contextual_quality(attempt, quality, seg, opts):
    if not (opts.get("source_pauses") or {}).get("enabled"):
        return quality
    raw, sr = sf.read(attempt["raw_path"],dtype="float32",always_2d=True)
    pauses = quiet_intervals(raw,sr)
    bounds = speech_bounds(to_mono(raw),sr,.005)
    start, end = (bounds[0]/sr,bounds[1]/sr) if bounds else (0, len(raw)/sr)
    duration = max(.01,end-start)
    source = seg.get("source_pauses") or []
    source_dur = max(.01,seg["end"]-seg["start"])
    used, matches, unmatched = set(), [], []
    for p in sorted(pauses,key=lambda p:p["duration"],reverse=True):
        position = ((p["start"]+p["end"])/2-start)/duration
        available = [(i,s) for i,s in enumerate(source) if i not in used and
                     abs(position-((s["start"]+s["end"])/2-seg["start"])/source_dur) <= .18 and
                     abs(p["duration"]-s["duration"]) <= max(.25,.35*s["duration"])]
        if available:
            i,s = min(available,key=lambda item:abs(item[1]["duration"]-p["duration"]))
            used.add(i); matches.append({"take":p,"source":s})
        else:
            unmatched.append(p)
    evidence = {"matched":matches,"unmatched":unmatched,"source":source,
                "missing_source": [s for i,s in enumerate(source) if i not in used],
                "scope":"approximate pause positions, no word or reaction realignment"}
    attempt["source_pause_evaluation"] = evidence
    reasons = list(quality.get("reasons") or [])
    # A global pause failure may be resolved only by positive, position-aware
    # source evidence. Every other failure is retained.
    hard = float(opts.get("pause_hard_sec",1.))
    if "pathological_pause" in reasons and pauses and not any(p["duration"] > hard for p in unmatched):
        reasons.remove("pathological_pause")
    attempt["raw_quality"] = quality
    return dict(quality,reasons=reasons,ok=not reasons,source_pause_evaluation=evidence)


def score_contextual(selection, attempt, opts):
    evidence = attempt.get("source_pause_evaluation")
    if evidence is None:
        return selection
    result = copy.deepcopy(selection)
    old = result["components"].get("pause",0.)
    # Penalize absent source pauses as well as unsupported generated pauses.
    penalty = sum(max(0.,p["duration"]-.45) for p in evidence["unmatched"])
    penalty += .5*sum(p["duration"] for p in evidence["missing_source"])
    result["components"]["pause"] = round(penalty,4)
    result["score"] = round(result["score"] + opts["weights"]["pause"]*(penalty-old),4)
    result["source_pause_evaluation"] = evidence
    return result
