"""Evidence-bound account of cues left out of an English export."""


def build_omission_report(job_id, status, export, export_sha256, validation_fingerprint, omitted, timeline):
    timeline_by_id = {int(s["id"]): s for s in timeline}
    rows = []
    for item in omitted:
        sid = int(item["id"])
        seg = timeline_by_id.get(sid, {})
        review = seg.get("translation_review") or {}
        reason = review.get("reason")
        rows.append({"id": sid, "start": item.get("start"), "end": item.get("end"),
                     "spanish": seg.get("spanish"), "english": seg.get("english"),
                     "category": review.get("status") if str(review.get("status", "")).startswith("withheld_") else item.get("status"),
                     "failure_reason": reason or item.get("timing_error") or item.get("status"),
                     "recovery_state": reason.get("reason") if isinstance(reason, dict) else None})
    return {"schema": "aidub.omissions.v1", "job_id": job_id, "status": status,
            "validation_fingerprint": validation_fingerprint, "export": str(export),
            "export_sha256": export_sha256, "omitted_count": len(rows), "omissions": rows}


def omissions_markdown(report):
    lines = [f"# Omitted cues ({report['status']})", "", f"Export: `{report['export']}`",
             f"SHA-256: `{report['export_sha256']}`", ""]
    for item in report["omissions"]:
        lines += [f"## ID {item['id']} — {item.get('start', 0):.3f}–{item.get('end', 0):.3f}s",
                  f"- Category: {item.get('category')}", f"- Reason: {item.get('failure_reason')}"]
        if item.get("spanish"):
            lines.append(f"- Spanish: {item['spanish']}")
        if item.get("english"):
            lines.append(f"- English: {item['english']}")
        lines.append("")
    return "\n".join(lines)
