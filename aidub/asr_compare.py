"""Evaluate Whisper models on one job's cues and second-pass spans instead of assuming one wins.

Every model must already be on disk. Agreement and confidence are reported per
window; they indicate consistency, not ground truth.
"""

from __future__ import annotations

import difflib
import os
from pathlib import Path

import numpy as np
import soundfile as sf

from .asr_client import AsrClient, whisper_python
from .config import named_whisper_model_file
from .job import Job
from .second_pass import es_tokens
from .util import read_json, write_json

KNOWN_SIZES = {"large-v3": "about 2.9 GB (large-v3.pt)", "large": "about 2.9 GB (large-v3.pt)",
               "large-v3-turbo": "about 1.5 GB", "turbo": "about 1.5 GB"}


def _require_weights(cfg: dict, model: str) -> Path:
    try:
        return named_whisper_model_file(cfg, model)
    except RuntimeError as exc:
        size = KNOWN_SIZES.get(model, "unknown size")
        raise RuntimeError(f"Whisper weights for {model!r} are not on this machine ({exc}). A download of {size} would be "
                           "required; aidub never downloads models. Provision the file yourself (or set "
                           "asr_second_pass.model_path) and rerun asr-compare.") from exc


def _windows(job: Job) -> list[dict]:
    timeline = read_json(job.dir / "timeline.json")["segments"]
    rows = [{"kind": "cue", "id": int(s["id"]), "lo": max(0.0, float(s["start"]) - 0.2), "hi": float(s["end"]) + 0.2,
             "first_pass": s["spanish"]} for s in timeline]
    corrections = read_json(job.dir / "transcribe/corrections.json")
    for n, gap in enumerate(corrections.get("untranscribed_energy") or []):
        rows.append({"kind": "voiced_gap", "id": n, "lo": max(0.0, gap["span"][0] - 0.35), "hi": gap["span"][1] + 0.35,
                     "first_pass": ""})
    return rows


def compare_models(job: Job, cfg: dict, models: list[str]) -> Path:
    if len(models) < 2:
        raise RuntimeError("asr-compare needs at least two models, e.g. --models turbo,large-v3")
    weights = {m: _require_weights(cfg, m) for m in models}
    alignment = read_json(job.dir / "extract/alignment.json")
    offset = float(alignment["offset_sec"])
    work = job.dir / "report/asr_compare"
    work.mkdir(parents=True, exist_ok=True)
    windows = _windows(job)
    with sf.SoundFile(job.dir / "extract/mic_raw.wav") as mic:
        for row in windows:
            lo = max(0, int(round((row["lo"] - offset) * mic.samplerate)))
            hi = min(mic.frames, int(round((row["hi"] - offset) * mic.samplerate)))
            mic.seek(lo)
            path = work / f"{row['kind']}_{row['id']:04d}.wav"
            tmp = path.with_name(path.stem + f".{os.getpid()}.tmp.wav")
            sf.write(tmp, mic.read(max(1, hi - lo), dtype="float32", always_2d=True), mic.samplerate, subtype="PCM_16")
            os.replace(tmp, path)
            row["path"] = str(path)
    options = dict((cfg.get("asr_second_pass") or {}).get("options") or {"condition_on_previous_text": False, "beam_size": 5})
    results = {m: [] for m in models}
    for model in models:
        client = AsrClient(whisper_python(cfg["executables"]["whisper"]), model=str(weights[model]),
                           device=str((cfg.get("asr_second_pass") or {}).get("device") or cfg["whisper"]["device"]),
                           log_path=work / f"{model}.log")
        try:
            for row in windows:
                raw = client.transcribe(row["path"], language=cfg["whisper"]["language"], word_timestamps=True,
                                        full_result=True, options=options)
                words = [w for seg in raw.get("segments") or [] for w in seg.get("words") or []]
                probs = [float(w.get("probability") or 0) for w in words]
                results[model].append({"text": (raw.get("text") or "").strip(),
                                       "mean_probability": round(float(np.mean(probs)), 4) if probs else None})
        finally:
            client.close()
    rows = []
    for k, row in enumerate(windows):
        entry = {key: row[key] for key in ("kind", "id", "lo", "hi", "first_pass")}
        entry["models"] = {m: results[m][k] for m in models}
        base = es_tokens(results[models[0]][k]["text"])
        entry["agreement_with_" + models[0]] = {
            m: round(difflib.SequenceMatcher(None, base, es_tokens(results[m][k]["text"])).ratio(), 3) for m in models[1:]}
        if row["first_pass"]:
            entry["agreement_with_first_pass"] = {
                m: round(difflib.SequenceMatcher(None, es_tokens(row["first_pass"]), es_tokens(results[m][k]["text"])).ratio(), 3)
                for m in models}
        rows.append(entry)
    summary = {m: {"mean_probability": round(float(np.mean([r["mean_probability"] for r in results[m] if r["mean_probability"] is not None] or [0])), 4),
                   "empty_windows": sum(1 for r in results[m] if not r["text"])} for m in models}
    report = {"schema": "aidub.asr_compare.v1", "models": models, "weights": {m: str(p) for m, p in weights.items()},
              "options": options, "summary": summary, "windows": rows,
              "note": "Agreement and confidence are consistency evidence, not ground truth; listen to disagreements."}
    write_json(job.dir / "report/asr_compare.json", report)
    lines = ["# ASR model comparison", "", report["note"], "", "| model | mean word probability | empty windows |", "| --- | --- | --- |"]
    for m in models:
        lines.append(f"| {m} | {summary[m]['mean_probability']} | {summary[m]['empty_windows']} |")
    lines += ["", "## Disagreements", ""]
    for entry in rows:
        texts = {m: entry["models"][m]["text"] for m in models}
        if len({" ".join(es_tokens(t)) for t in texts.values()}) > 1:
            lines.append(f"- {entry['kind']} {entry['id']} ({entry['lo']:.2f}–{entry['hi']:.2f}s): "
                         + " | ".join(f"{m}: `{t}`" for m, t in texts.items()))
    (job.dir / "report/asr_compare.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return job.dir / "report/asr_compare.md"
