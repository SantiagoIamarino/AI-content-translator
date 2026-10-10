#!/usr/bin/env python3
"""Before/after comparison of two finished jobs on the same source.

Writes COMPARISON.md, comparison.json, matched listening excerpts and short
previews into a new output directory. Measurements are technical proxies;
they do not establish that either dub sounds natural.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aidub.textnorm import english_syllables, normalize_tokens  # noqa: E402
from aidub.util import read_json, write_json  # noqa: E402


def job_metrics(job: Path) -> dict:
    summary = read_json(job / "mix/placed_summary.json")
    validation = read_json(job / "report/validation.json")
    corrections = read_json(job / "transcribe/corrections.json")
    rows = summary["segments"]
    placed = [r for r in rows if r.get("placed")]
    rates, overrun = [], []
    for r in placed:
        core = float(r.get("trim_duration_sec") or 0) / float(r.get("tempo") or 1.0)
        if core > 0 and english_syllables(r["english"]) >= 3:
            rates.append(english_syllables(r["english"]) / core)
        overrun.append(max(0.0, float(r["placement_end"]) - float(r["end"])))
    english = [r["english"].strip().lower() for r in rows]
    repeated_adjacent = [rows[i + 1]["id"] for i in range(len(rows) - 1)
                         if english[i] == english[i + 1] and rows[i]["spanish"].strip().lower() != rows[i + 1]["spanish"].strip().lower()]
    overlap_src = [rows[i + 1]["id"] for i in range(len(rows) - 1) if float(rows[i + 1]["start"]) < float(rows[i]["end"]) - 1e-3]
    gaps = corrections.get("untranscribed_energy") or []
    outcomes = {}
    for g in gaps:
        key = (g.get("second_pass") or {}).get("outcome", "unreviewed")
        outcomes[key] = outcomes.get(key, 0) + 1
    generated = sum(len(r.get("attempts") or []) for r in rows)
    return {
        "status": validation["status"],
        "failed_checks": [c["name"] for c in validation["checks"] if c.get("required", True) and c["ok"] is not True],
        "cues": len(rows), "placed": len(placed),
        "tempo_adjusted": sum(1 for r in placed if float(r.get("tempo") or 1) > 1.0001),
        "max_tempo": round(max([float(r.get("tempo") or 1) for r in placed] or [1.0]), 3),
        "leading_shift": sum(1 for r in placed if r.get("leading_shift_sec")),
        "syllables_per_sec_median": round(float(np.median(rates)), 2) if rates else None,
        "syllables_per_sec_p90": round(float(np.percentile(rates, 90)), 2) if rates else None,
        "mean_overrun_past_spanish_end_sec": round(float(np.mean(overrun)), 3) if overrun else None,
        "max_overrun_past_spanish_end_sec": round(float(np.max(overrun)), 3) if overrun else None,
        "same_english_on_adjacent_different_spanish": repeated_adjacent,
        "overlapping_source_cues": overlap_src,
        "untranscribed_gaps": len(gaps), "gap_outcomes": outcomes,
        "takes_generated": generated,
        "presentation_versions": sorted({(r.get("presentation") or {}).get("version", 1) for r in placed}),
        "tempo_lines_with_loudness_gain": sum(1 for r in placed if float(r.get("tempo") or 1) > 1.0001 and r.get("loudness_gain") is not None),
    }


def _slice(path: Path, lo: float, hi: float, offset: float = 0.0):
    with sf.SoundFile(path) as h:
        a = max(0, int((lo - offset) * h.samplerate))
        b = min(h.frames, int((hi - offset) * h.samplerate))
        h.seek(a)
        return h.read(max(1, b - a), dtype="float32", always_2d=True), h.samplerate


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("baseline")
    ap.add_argument("candidate")
    ap.add_argument("out")
    ap.add_argument("--ffmpeg", default="ffmpeg")
    args = ap.parse_args()
    base, cand, out = Path(args.baseline), Path(args.candidate), Path(args.out)
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"{out} exists and is not empty; choose a new directory")
    (out / "excerpts").mkdir(parents=True, exist_ok=True)
    (out / "previews").mkdir(parents=True, exist_ok=True)
    metrics = {"baseline": job_metrics(base), "candidate": job_metrics(cand)}
    b_rows = read_json(base / "mix/placed_summary.json")["segments"]
    c_rows = read_json(cand / "mix/placed_summary.json")["segments"]
    c_tl = {int(s["id"]): s for s in read_json(cand / "timeline.json")["segments"]}
    risk = read_json(cand / "report/risk.json") if (cand / "report/risk.json").is_file() else {"items": []}
    risk_by_id = {i["id"]: i for i in risk["items"] if i.get("id") is not None}
    lines = []
    for r in c_rows:
        lo, hi = float(r["start"]), float(r["end"])
        before = [b for b in b_rows if float(b["start"]) < hi + 0.05 and float(b["end"]) > lo - 0.05]
        review = (c_tl.get(int(r["id"])) or {}).get("translation_review") or {}
        lines.append({"id": r["id"], "start": lo, "end": hi, "spanish": r["spanish"], "english": r["english"],
                      "english_draft": review.get("draft"), "review_status": review.get("status"),
                      "risk_score": (risk_by_id.get(r["id"]) or {}).get("score"),
                      "baseline": [{"id": b["id"], "spanish": b["spanish"], "english": b["english"]} for b in before]})
    changed = [l for l in lines
               if normalize_tokens(" ".join(b["english"] for b in l["baseline"])) != normalize_tokens(l["english"])]
    for l in lines:
        l["changed_words"] = l in changed
    top = sorted([l for l in lines if l["risk_score"]], key=lambda l: -l["risk_score"])[:6]
    picks = {l["id"]: l for l in changed[:10] + top}
    alignment = read_json(cand / "extract/alignment.json")
    container = "mp4"
    for line in sorted(picks.values(), key=lambda l: l["start"]):
        lo = max(0.0, line["start"] - 0.6)
        hi = line["end"] + 1.2
        tag = f"t{lo:07.2f}_id{line['id']:03d}".replace(".", "_")
        files = {}
        mic, sr = _slice(cand / "extract/mic_raw.wav", lo, hi, float(alignment["offset_sec"]))
        files["spanish_mic"] = out / "excerpts" / f"{tag}_spanish_mic.wav"
        sf.write(files["spanish_mic"], mic, sr, subtype="PCM_16")
        for label, job in (("baseline_mix", base), ("candidate_mix", cand)):
            audio, rate = _slice(job / "output/english_mix.wav", lo, hi)
            files[label] = out / "excerpts" / f"{tag}_{label}.wav"
            sf.write(files[label], audio, rate, subtype="PCM_16")
        for label, job in (("baseline", base), ("candidate", cand)):
            video = Path(read_json(job / "report/validation.json")["english_video"])
            dest = out / "previews" / f"{tag}_{label}.mp4"
            cmd = [args.ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{max(0, lo - 1):.3f}", "-t",
                   f"{hi - lo + 2:.3f}", "-i", str(video), "-map", "0:v:0", "-map", "0:a:0", "-c:v", "libx264",
                   "-preset", "veryfast", "-crf", "23", "-vf", "scale=-2:720", "-c:a", "aac", "-b:a", "160k", str(dest)]
            if subprocess.run(cmd, capture_output=True, timeout=300).returncode == 0:
                files[label + "_preview"] = dest
        line["excerpts"] = {k: str(v) for k, v in files.items()}
    write_json(out / "comparison.json", {"baseline": str(base), "candidate": str(cand), "metrics": metrics, "lines": lines})
    md = ["# Before/after comparison", "", f"- Baseline: `{base}`", f"- Candidate: `{cand}`", "",
          "Technical measurements and text differences below do not establish perceived naturalness. Listen to the excerpts.",
          "", "## Metrics", "", "| metric | baseline | candidate |", "| --- | --- | --- |"]
    for key in metrics["baseline"]:
        md.append(f"| {key} | {metrics['baseline'][key]} | {metrics['candidate'][key]} |")
    md += ["", "## Lines (candidate cues with time-overlapping baseline cues)", ""]
    for l in lines:
        md.append(f"### id {l['id']} — {l['start']:.2f}–{l['end']:.2f}s" + (f" — risk {l['risk_score']}" if l["risk_score"] else ""))
        md.append(f"- ES: {l['spanish']}")
        for b in l["baseline"]:
            md.append(f"- baseline id {b['id']}: ES `{b['spanish']}` → EN `{b['english']}`")
        if l.get("english_draft") and l["english_draft"] != l["english"]:
            md.append(f"- candidate draft: {l['english_draft']}")
        md.append(f"- candidate: **{l['english']}**" + (f" ({l['review_status']})" if l.get("review_status") else ""))
        for k, v in (l.get("excerpts") or {}).items():
            md.append(f"- {k}: `{v}`")
        md.append("")
    (out / "COMPARISON.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(out / "COMPARISON.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
