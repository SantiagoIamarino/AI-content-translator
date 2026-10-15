"""Focused, cached hearings for fillers normalized away in long-sentence ASR.

No expected-text prompt is supplied. Two different short audio windows must agree
on the required prefix. This is corroborating ASR evidence, not listening approval.
"""
from pathlib import Path

import soundfile as sf

from .events import has_event_prefix
from .util import fingerprint, read_json, write_json, sha256_file


def verify_prefix(directory, meta, prefix, identity, transcribe, *, retry=True):
    started = identity()
    key = fingerprint({"waveform":sha256_file(Path(meta["path"])),"prefix":prefix,
                       "verification":started,"code":sha256_file(Path(__file__)),"windows":[.55,.8,1.1]})
    cache = directory/"cache/prefix_quality"/f"{key}.json"
    if cache.is_file():
        result = read_json(cache)
        if result.get("key") == key:
            return dict(result,cache_hit=True)
    audio,sr=sf.read(meta["path"],dtype="float32",always_2d=True)
    records=[]; matches=0
    for seconds in (.55,.8,1.1):
        path=directory/"cache/prefix_windows"/f"{key}_{seconds}.wav"
        path.parent.mkdir(parents=True,exist_ok=True)
        sf.write(path,audio[:round(seconds*sr)],sr,subtype="FLOAT")
        hearing=transcribe(str(path))
        if identity()!=started:
            if retry:
                return verify_prefix(directory,meta,prefix,identity,transcribe,retry=False)
            return {"verified":False,"reason":"verification_environment_changed","hearings":records}
        match=has_event_prefix(hearing.get("text"),prefix)
        records.append({"seconds":seconds,"match":match,**hearing})
        matches+=int(match)
        if matches>=2:
            break
    result={"key":key,"verified":matches>=2,"hearings":records,"verification_identity":started,
            "scope":"same recognizer, distinct prefix windows, no expected-text prompt",
            "low_confidence":any((r.get("mean_probability") or 0)<.5 for r in records if r["match"])}
    write_json(cache,result)
    return dict(result,cache_hit=False)
