"""Identity-bound acceptance of a bounded acoustic/bilingual review subset."""
from pathlib import Path

from .job import Job
from .pipeline import _save_timeline, translation_fingerprint
from .review import validate_review_response, review_decision
from .util import fingerprint, read_json, sha256_file, write_json


def accept_targeted_review(job: Job, request_path: Path, response_path: Path,
                           acoustic_report_path: Path) -> dict:
    request_path = Path(request_path).resolve()
    response_path = Path(response_path).resolve()
    acoustic_report_path = Path(acoustic_report_path).resolve()
    request = read_json(request_path)
    response = read_json(response_path)
    acoustic = read_json(acoustic_report_path)
    if request.get("schema") != "aidub.review_request.v1" or request.get("job_id") != job.data["job_id"]:
        raise RuntimeError("Targeted review request schema/job identity does not match this job")
    identity = fingerprint(request)
    if response.get("_aidub_request_identity") != identity:
        raise RuntimeError("Targeted review response request identity does not match")
    provider = response.get("translator") or {}
    if provider.get("kind") != "command" or provider.get("model") != "gpt-6-luna":
        raise RuntimeError("Targeted review response is not identified as gpt-6-luna")
    if acoustic.get("job_id") != job.data["job_id"] or not acoustic.get("complete"):
        raise RuntimeError("Targeted acoustic report is incomplete or belongs to another job")

    segments = job.data.get("timeline") or []
    by_id = {int(s["id"]): s for s in segments}
    rows = request.get("segments") or []
    ids = [int(r["id"]) for r in rows]
    if not ids or len(ids) != len(set(ids)):
        raise RuntimeError("Targeted review must contain unique cue IDs")
    acoustic_by_id = {int(r["id"]): r for r in acoustic.get("results") or []}
    for row in rows:
        sid = int(row["id"])
        seg = by_id.get(sid)
        evidence = acoustic_by_id.get(sid)
        targeted = row.get("targeted_acoustic_evidence") or {}
        if not seg or not evidence:
            raise RuntimeError(f"Cue {sid} is missing from the current timeline or acoustic evidence")
        if row.get("spanish") != seg.get("spanish") or row.get("english") != seg.get("english"):
            raise RuntimeError(f"Cue {sid} changed after the targeted review request was built")
        if (targeted.get("primary") != seg.get("spanish") or
                targeted.get("saved_alternatives") != seg.get("asr_alternatives", []) or
                targeted.get("contextual_hypothesis") != (evidence.get("hypothesis") or {}).get("text") or
                targeted.get("review_span") != evidence.get("review_span")):
            raise RuntimeError(f"Cue {sid} acoustic evidence does not match the saved targeted review")
    current = {sid: by_id[sid].get("english") or "" for sid in ids}
    errors = validate_review_response(request, response, current)
    if errors:
        raise RuntimeError("Targeted review response rejected:\n- " + "\n- ".join(errors))

    response_by_id = {int(r["id"]): r for r in response["segments"]}
    evidence_sha = sha256_file(acoustic_report_path)
    request_rel = str(request_path.relative_to(job.dir))
    response_rel = str(response_path.relative_to(job.dir))
    acoustic_rel = str(acoustic_report_path.relative_to(job.dir))
    accepted = disputed = revised = 0
    for row in rows:
        sid = int(row["id"])
        seg = by_id[sid]
        verdict = response_by_id[sid]
        old_english = seg.get("english") or ""
        new_english = verdict.get("english", old_english).strip()
        issues = sorted(set(verdict.get("issues") or []))
        decision = review_decision(verdict, old_english, new_english,
                                   material_conflict=seg.get("material_source_conflict"))
        source_disputed = decision["source_disputed"]
        status = decision["status"]
        if status == "accepted_draft":
            status = "accepted_targeted_review"
        if new_english != old_english:
            seg["english"] = new_english
            revised += 1
        seg.setdefault("targeted_review_history", []).append({
            "request_identity": identity,
            "request": request_rel,
            "response": response_rel,
            "acoustic_report": acoustic_rel,
            "acoustic_report_sha256": evidence_sha,
            "provider": response["translator"],
            "verdict": verdict["verdict"],
            "disputed": source_disputed,
            "issues": issues,
            "reason": verdict.get("reason"),
            "english_before": old_english,
            "english_after": new_english,
        })
        seg["translation_review"] = {
            "status": status,
            "draft": old_english,
            "checked_text": new_english,
            "issues": issues,
            "targeted_review_request_identity": identity,
            "targeted_review_response": response_rel,
        }
        if status in {"disputed", "revised_unconfirmed"}:
            disputed += 1
        else:
            accepted += 1

    job.stage("translation").update(status="complete", fingerprint=translation_fingerprint(segments))
    for name in ("schedule", "mix", "validate"):
        job.stage(name)["status"] = "pending"
        job.stage(name)["fingerprint"] = None
    _save_timeline(job)
    summary = {"request_identity": identity, "provider": response["translator"],
               "acoustic_report_sha256": evidence_sha, "reviewed": len(ids),
               "accepted_for_scheduling": accepted, "kept_disputed": disputed,
               "english_revised": revised, "request": request_rel,
               "response": response_rel, "acoustic_report": acoustic_rel}
    write_json(job.dir / "report/targeted_review_acceptance.json", summary)
    return summary
