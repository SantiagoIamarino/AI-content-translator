"""Risk-ranked evaluation report with listening excerpts and short playable previews.

The ranking points a listener at the lines most likely to be wrong or unnatural.
It is evidence for evaluation, not an approval and not a repair queue.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

from .util import fingerprint, read_json, sha256_file, write_json


def _read(path: Path, start: float, end: float, offset: float = 0.0) -> tuple[np.ndarray, int]:
    with sf.SoundFile(path) as handle:
        sr = handle.samplerate
        lo = max(0, int(round((start - offset) * sr)))
        hi = min(handle.frames, int(round((end - offset) * sr)))
        if hi <= lo:
            return np.zeros((0, handle.channels), dtype=np.float32), sr
        handle.seek(lo)
        return handle.read(hi - lo, dtype="float32", always_2d=True), sr


def line_risk(row: dict, seg: dict, audit_line: dict | None) -> tuple[float, list[str]]:
    reasons, score = [], 0.0

    def add(points, text):
        nonlocal score
        score += points
        reasons.append(text)

    if not row.get("placed"):
        add(6, f"unplaced: {row.get('timing_error') or row.get('status')}")
    status = (audit_line or {}).get("status")
    if status == "disputed":
        add(4, "reviewer marked the source/translation as disputed")
    elif status == "revised_unconfirmed":
        add(3, "last review round revised this line; no confirming round remained")
    elif status == "revised_confirmed":
        issues = sorted({i for r in (audit_line or {}).get("rounds") or [] for i in r.get("issues") or []})
        add(1, "review corrected the draft (" + ", ".join(issues) + ")")
    if (audit_line or {}).get("back_translations"):
        add(1, "back-translation requested: " + audit_line["back_translations"][-1]["spanish"])
    if seg.get("asr_alternatives"):
        add(2, "second ASR hearing differs: " + "; ".join(a["text"] for a in seg["asr_alternatives"]))
    uncertain = seg.get("uncertain_words") or []
    if uncertain:
        add(min(3, len(uncertain)), "low-confidence source words: " + ", ".join(str(w.get("word")) for w in uncertain[:5]))
    if seg.get("recovered"):
        add(2, "cue recovered from voiced energy by the second ASR hearing")
    notes = seg.get("notes") or ""
    if "Possible ASR duplicate" in notes:
        add(2, "possible duplicated source phrase was not resolved")
    quality = row.get("quality") or {}
    text = quality.get("text_check") or {}
    if quality.get("second_verification"):
        add(1.5, "synthesized text needed a second ASR verification")
    if quality.get("short_phrase_unverified"):
        add(1, "short phrase could not be confirmed by ASR")
    if text.get("soft"):
        add(1, "minor ASR differences: " + ", ".join(text["soft"]))
    selection = row.get("selection_summary") or {}
    if selection:
        if selection.get("valid", 0) <= 1:
            add(2, f"only {selection.get('valid', 0)} valid take(s) of {selection.get('generated', 0)}")
        chosen = selection.get("chosen") or {}
        comps = chosen.get("components") or {}
        if comps.get("pace", 0) > 0.15:
            add(1.5, f"speaking rate outside the natural band ({(chosen.get('pacing') or {}).get('rate')} syl/s)")
        if comps.get("pause", 0) > 0.15:
            add(1, f"long internal pause ({(chosen.get('pacing') or {}).get('longest_pause_sec')} s)")
        if (chosen.get("voice_distance_running") or 0) > 1.0 or (chosen.get("voice_distance_reference") or 0) > 1.2:
            add(2, "voice features far from the reference or the rest of the job")
    tempo = float(row.get("tempo") or 1.0)
    if tempo > 1.05:
        add(1, f"tempo {tempo:.3f}")
    if row.get("leading_shift_sec"):
        add(0.5, f"started {row['leading_shift_sec']:.2f}s early")
    budget = seg.get("syllable_budget") or {}
    if budget.get("over_max"):
        add(1, f"English {budget.get('syllables')} syllables over max {budget.get('max')}")
    if row.get("revisions"):
        add(1, f"compact revision: {row['revisions'][-1].get('reason')}")
    return round(score, 2), reasons


def build_risk_report(job_dir: Path, cfg: dict, limit: int = 12, previews: bool = True) -> dict:
    summary = read_json(job_dir / "mix/placed_summary.json")
    timeline = {int(s["id"]): s for s in read_json(job_dir / "timeline.json")["segments"]}
    audit_path = job_dir / "handoff/translation_audit.json"
    audit = read_json(audit_path) if audit_path.is_file() else {}
    lines_audit = audit.get("lines") or {}
    second = read_json(job_dir / "transcribe/second_pass.json") if (job_dir / "transcribe/second_pass.json").is_file() else {}
    corrections = read_json(job_dir / "transcribe/corrections.json")
    validation = read_json(job_dir / "report/validation.json") if (job_dir / "report/validation.json").is_file() else {}
    alignment = read_json(job_dir / "extract/alignment.json")
    offset = float(alignment["offset_sec"])
    items = []
    for row in summary["segments"]:
        sid = int(row["id"])
        seg = timeline.get(sid, {})
        score, reasons = line_risk(row, seg, lines_audit.get(str(sid)))
        items.append({"kind": "line", "id": sid, "score": score, "reasons": reasons, "start": row["start"],
                      "end": row["end"], "placement_start": row.get("placement_start"), "placement_end": row.get("placement_end"),
                      "spanish": row.get("spanish"), "english": row.get("english"),
                      "english_draft": (lines_audit.get(str(sid)) or {}).get("draft"),
                      "review_status": (lines_audit.get(str(sid)) or {}).get("status"), "placed": row.get("placed")})
    for gap in corrections.get("untranscribed_energy") or []:
        outcome = (gap.get("second_pass") or {}).get("outcome") or "unreviewed"
        if outcome in {"recovered", "non_speech_energy", "covered_by_existing_cue", "already_transcribed"}:
            continue
        points = {"unintelligible": 2.5, "no_speech_heard": 1.0}.get(outcome, 3.0)
        items.append({"kind": "voiced_gap", "id": None, "score": points, "start": gap["span"][0], "end": gap["span"][1],
                      "reasons": [f"voiced source energy without English ({outcome})"
                                  + (f"; second hearing: {gap['second_pass'].get('text')}" if (gap.get("second_pass") or {}).get("text") else "")],
                      "spanish": None, "english": None})
    items.sort(key=lambda r: (-r["score"], r["start"]))
    excerpt_dir = job_dir / "report/excerpts"
    preview_dir = job_dir / "report/previews"
    excerpt_dir.mkdir(parents=True, exist_ok=True)
    english_video = Path(validation.get("english_video") or "")
    container = (cfg.get("export") or {}).get("container", "mp4")
    spanish_video = job_dir / f"output/spanish_compare.{container}"
    ffmpeg = cfg["executables"]["ffmpeg"]
    for item in [i for i in items if i["score"] > 0][:limit]:
        tag = f"id{item['id']:03d}" if item["id"] is not None else f"gap_{item['start']:08.2f}".replace(".", "_")
        lo = min(item["start"], item.get("placement_start") or item["start"]) - 0.4
        hi = max(item["end"], item.get("placement_end") or item["end"]) + 0.4
        lo = max(0.0, lo)
        files = {}
        mic, sr = _read(job_dir / "extract/mic_raw.wav", lo, hi, offset)
        files["spanish_mic"] = excerpt_dir / f"{tag}_spanish_mic.wav"
        sf.write(files["spanish_mic"], mic, sr, subtype="PCM_16")
        for label, name in (("english_voice", "english_voice.wav"), ("english_mix", "english_mix.wav")):
            audio, rate = _read(job_dir / "output" / name, lo, hi)
            files[label] = excerpt_dir / f"{tag}_{label}.wav"
            sf.write(files[label], audio, rate, subtype="PCM_16")
        if previews and english_video.is_file():
            preview_dir.mkdir(parents=True, exist_ok=True)
            p_lo, p_dur = max(0.0, lo - 1.0), (hi - lo) + 2.0
            for label, source in (("preview_en", english_video), ("preview_es", spanish_video)):
                if not source.is_file():
                    continue
                dest = preview_dir / f"{tag}_{label[-2:]}.mp4"
                cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{p_lo:.3f}", "-t", f"{p_dur:.3f}",
                       "-i", str(source), "-map", "0:v:0", "-map", "0:a:0", "-c:v", "libx264", "-preset", "veryfast",
                       "-crf", "23", "-vf", "scale=-2:720", "-c:a", "aac", "-b:a", "160k", str(dest)]
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
                if proc.returncode == 0:
                    files[label] = dest
        item["excerpts"] = {k: str(v) for k, v in files.items()}
    report = {
        "schema": "aidub.risk_report.v1",
        "job_id": job_dir.name,
        "status": validation.get("status"),
        "note": "Risk ranking is evidence for listening, not an approval or a repair queue.",
        "counts": {
            "lines": len(summary["segments"]),
            "review_revised": sum(1 for v in lines_audit.values() if v.get("status", "").startswith("revised")),
            "review_disputed": sum(1 for v in lines_audit.values() if v.get("status") == "disputed"),
            "second_pass_targets": len(second.get("targets") or []),
            "recovered_cues": second.get("recovered", 0),
            "dropped_duplicates": len(second.get("dropped_duplicates") or []),
        },
        "items": items,
    }
    write_json(job_dir / "report/risk.json", report)
    (job_dir / "report/risk.md").write_text(risk_markdown(report), encoding="utf-8")
    return report


def risk_markdown(report: dict) -> str:
    lines = [f"# Risk report ({report.get('status')})", "", report["note"], "",
             "Technical checks and these scores do not prove that a line sounds natural.", "", "## Counts", ""]
    for key, value in report["counts"].items():
        lines.append(f"- {key}: {value}")
    lines += ["", "## Ranked items", ""]
    for item in report["items"]:
        if item["score"] <= 0:
            continue
        head = f"id {item['id']}" if item["id"] is not None else "voiced gap"
        lines.append(f"### {head} — score {item['score']} — {item['start']:.2f}–{item['end']:.2f}s")
        if item.get("spanish"):
            lines.append(f"- ES: {item['spanish']}")
        if item.get("english_draft") and item.get("english_draft") != item.get("english"):
            lines.append(f"- EN draft: {item['english_draft']}")
        if item.get("english"):
            lines.append(f"- EN: {item['english']}")
        for reason in item["reasons"]:
            lines.append(f"- {reason}")
        for label, path in (item.get("excerpts") or {}).items():
            lines.append(f"- {label}: `{path}`")
        lines.append("")
    quiet = [i for i in report["items"] if i["score"] <= 0]
    lines += ["## Lines without risk signals", "", ", ".join(str(i["id"]) for i in quiet) or "None.", ""]
    return "\n".join(lines)


def risk_fingerprint(job_dir: Path) -> str:
    paths = ["mix/placed_summary.json", "timeline.json", "handoff/translation_audit.json", "transcribe/second_pass.json",
             "transcribe/corrections.json", "report/validation.json", "output/english_mix.wav"]
    return fingerprint({p: sha256_file(job_dir / p) if (job_dir / p).is_file() else None for p in paths} | {"version": 1})
