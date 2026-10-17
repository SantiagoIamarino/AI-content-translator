#!/usr/bin/env python3
"""Offline comparison only: never instantiate Job, lock, call, synthesize or export.

Run with the configured interpreter and this checkout on PYTHONPATH. Output must
be outside the input job. Historical validators are loaded from the pre-correction
commit so that deterministic replay and classification effects stay separate.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import subprocess
from unittest.mock import patch

from aidub.fidelity import eligibility
from aidub.saved_decisions import replay_saved_batch, restore_current_decision
from aidub.source_disagreement import disagreement, bind_comparison_evidence
from aidub.util import read_json, write_json, fingerprint
import aidub.source_resolution as resolution

ROOT = Path(__file__).resolve().parents[1]


def historical(module):
    code = subprocess.check_output(["git", "show", "2384395:aidub/" + module + ".py"], cwd=ROOT).decode()
    namespace = {"__package__": "aidub", "__name__": "aidub._baseline_" + module}
    exec(compile(code, module + "@2384395", "exec"), namespace)
    return namespace


def signature(job):
    # Byte hashes of small authoritative inputs; metadata only for media/caches.
    small = ["config.json", "manifest.json", "timeline.json", "handoff/source_resolution/state.json",
             "schedule/summary.json", "report/omissions.json", "report/validation.json"]
    return {"inputs": {p: hashlib.sha256((job / p).read_bytes()).hexdigest() for p in small},
            "tree": fingerprint([(str(p.relative_to(job)), p.stat().st_size, p.stat().st_mtime_ns)
                                 for p in sorted(job.rglob("*")) if p.is_file()])}


def recover(job, timeline, spec):
    events, receipts = [], []
    for base in (job / "handoff/batches/review", job / "handoff/source_resolution/responses/batches/review"):
        for directory in sorted(base.glob("*/batch_*")):
            states = sorted(directory.glob("response_attempts/*/state.json"))
            if not states:
                continue
            state = read_json(states[0])
            request = read_json(Path(state["attempts"][0]["request_path"]))
            request.pop("validation_feedback", None)
            replay = replay_saved_batch(spec, request, directory, "review", {s["id"]: s["english"] for s in request["segments"]})
            for receipt in replay["receipts"].values():
                state = read_json(Path(receipt["state_path"]))
                stamp = max((a.get("ended_at") or a.get("started_at") or 0 for a in state["attempts"]
                             if a.get("response_path") == receipt["response_path"]), default=0)
                receipts.append((float(stamp), receipt))
    out = {s["id"]: copy.deepcopy(s) for s in timeline}
    mic = read_json(job / "extract/alignment.json")["mic_sha256"]
    for _, receipt in sorted(receipts, key=lambda r: (r[0], r[1]["response_path"])):
        sid = receipt["source"]["id"]
        if sid not in out:
            continue
        # A recovery repairs absent/withheld acceptance. It must not replace an
        # already accepted audit, or an explicit source adjudication, with an
        # older historical review of the same text.
        original = next(s for s in timeline if s["id"] == sid)
        if receipt["source"].get("source_evidence"):
            if original.get("source_resolution"):
                continue
        elif (original.get("translation_review") or {}).get("status") not in {
                "withheld_review_failure", "withheld_translation_failure"}:
            continue
        restored, reason = restore_current_decision(out[sid], receipt, mic)
        events.append({"id": sid, "reason": reason, "receipt": receipt})
        out[sid] = restored
    return out, events


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job", type=Path); parser.add_argument("out", type=Path)
    args = parser.parse_args(); job = args.job.resolve(); out = args.out.resolve()
    if job == out or job in out.parents or out.exists():
        raise RuntimeError("Choose a new isolated output directory outside the job")
    import aidub
    assert Path(aidub.__file__).resolve().parent == ROOT / "aidub"
    preserved = signature(job)
    cfg = read_json(job / "config.json"); timeline = read_json(job / "timeline.json")["segments"]
    mic = read_json(job / "extract/alignment.json")["mic_sha256"]
    omissions = {r["id"]: r for r in read_json(job / "report/omissions.json")["omissions"]}
    old_eligible = historical("fidelity")["eligibility"]
    with patch.object(resolution, "assessment_errors", historical("source_resolution")["assessment_errors"]):
        first, first_events = recover(job, timeline, cfg["providers"]["review"])
    final, events = recover(job, timeline, cfg["providers"]["review"])
    evidence = {e["id"]: e.get("evidence", {}) for e in read_json(job / "handoff/source_resolution/state.json")["episodes"].values()}
    final = {sid: bind_comparison_evidence(s, evidence.get(sid, {}), mic) for sid, s in final.items()}
    rows = []
    for seg in timeline:
        sid = seg["id"]
        if sid not in omissions:
            continue
        before = old_eligible(seg, cfg, mic); step1 = old_eligible(first[sid], cfg, mic); after = eligibility(final[sid], cfg, mic)
        proof = [e for e in events if e["id"] == sid and e["reason"].startswith("replayed_")]
        classification = disagreement(final[sid])
        changed = before != after
        reasons = []
        if first[sid].get("translation_review") != seg.get("translation_review"):
            reasons.append("identity-bound raw decision replay; obsolete marker superseded only by validated current decision")
        if step1 != after:
            reasons.append("classified differences: " + classification["kind"] + "; " +
                           "; ".join(dict.fromkeys(c["reason"] for c in classification["comparisons"])))
        if before == after:
            reasons.append("no eligibility change; " + (after["reason"] or "still eligible, normal synthesis/placement rejection unchanged"))
        rows.append({"id": sid, "start": seg["start"], "end": seg["end"], "window_seconds": seg["end"] - seg["start"],
                     "spanish": seg["spanish"], "english": seg.get("english"), "export_failure": omissions[sid]["failure_reason"],
                     "before": before, "after_deterministic": step1, "after": after, "changed": changed,
                     "reasons": reasons, "classification": classification, "validated_decisions": proof})
    regressions = [s["id"] for s in timeline if s["id"] not in omissions and
                   eligibility(final[s["id"]], cfg, mic)["synthesis"] == "withheld"]
    assert len(rows) == 115
    assert not regressions, ("previously placed cues newly withheld", regressions)
    assert {83, 123, 523, 655} <= {r["id"] for r in rows if r["after_deterministic"]["synthesis"] != "withheld"}
    assert next(r for r in rows if r["id"] == 676)["after"]["synthesis"] == "withheld"
    assert next(r for r in rows if r["id"] == 234)["after"]["synthesis"] == "withheld"
    gained = [r for r in rows if r["before"]["synthesis"] == "withheld" and r["after"]["synthesis"] != "withheld"]
    step1_gained = [r for r in rows if r["before"]["synthesis"] == "withheld" and r["after_deterministic"]["synthesis"] != "withheld"]
    summary = {"omitted_compared": len(rows), "deterministic_gains": [r["id"] for r in step1_gained],
               "eligibility_gains": [r["id"] for r in gained], "gain_source_windows_seconds": sum(r["window_seconds"] for r in gained),
               "newly_withheld_previously_placed": regressions,
               "note": "Eligibility only. No synthesized/placed gain established; source windows are not measured lost speech."}
    assert preserved == signature(job), "Input job changed during evaluation"
    out.mkdir(parents=True)
    write_json(out / "comparison.json", {"summary": summary, "rows": rows})
    write_json(out / "replay_events.json", {"deterministic": first_events, "current": events})
    write_json(out / "eligible_timeline.json", {"segments": list(final.values())})
    write_json(out / "preservation.json", preserved)
    write_json(out / "identity.json", {"head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip(),
              "tracked_diff_sha256": hashlib.sha256(subprocess.check_output(["git", "diff", "HEAD"], cwd=ROOT)).hexdigest(),
              "module": str(Path(aidub.__file__).resolve()), "config_sha256": preserved["inputs"]["config.json"],
              "baseline": "2384395", "provider_calls": 0, "job_locks": 0})
    lines = ["# Isolated coverage comparison", "", json.dumps(summary, ensure_ascii=False, indent=2), "",
             "| Cue | Seconds | Export reason | Before | After replay | After classification | Explanation |",
             "|---|---:|---|---|---|---|---|"]
    for r in rows:
        label = lambda d: d["synthesis"] + ":" + (d["reason"] or "eligible")
        lines.append(f"| {r['id']} | {r['start']:.3f}–{r['end']:.3f} | {r['export_failure']} | {label(r['before'])} | {label(r['after_deterministic'])} | {label(r['after'])} | {'; '.join(r['reasons']).replace('|', '/')} |")
    (out / "comparison.md").write_text("\n".join(lines) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
