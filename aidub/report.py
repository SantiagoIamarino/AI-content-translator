from .srt import omitted_lines


def validation_markdown(summary: dict) -> str:
    status = summary["status"]
    video = summary.get("english_video") or ""
    lines = [
        f"# Validation report ({status})",
        "",
        f"English video: `{video}`",
        "",
        "Technical start-time match is not perceptual sync. This report does not approve voice quality.",
        "",
        "## Result",
        "",
        f"- Job: `{summary['job_id']}`",
        f"- Status: **{status}**",
        f"- Segments: {summary['n_segments']}",
        f"- Placed: {summary['n_placed']}",
        f"- Unplaced: {summary['n_unplaced']}",
        f"- Tempo adjusted: {summary['n_tempo']}",
        f"- Alternate-seed attempts: {summary['n_alternate']}",
        f"- Compact revisions: {summary['n_revisions']}",
        f"- Fresh synthesis this schedule pass: {summary['n_synth_fresh']}",
        f"- Cache hits this schedule pass: {summary['n_synth_cache_hits']}",
        f"- Mix gain: {summary['mix']['gain']}",
        f"- Mix peak: {summary['mix']['mix_peak']}",
        f"- Clipping samples: {summary['mix']['clipping_samples']}",
        "",
        "## Unplaced / omitted from SRT",
        "",
    ]
    omitted = summary.get("omitted") or []
    if not omitted:
        lines.append("None.")
    else:
        for row in omitted:
            lines.append(
                f"- id {row['id']}: {row.get('timing_error') or row.get('status')} — EN `{row.get('english')}` / ES `{row.get('spanish')}`"
            )
    lines += ["", "## Repairs", ""]
    repairs = summary.get("repairs") or []
    if not repairs:
        lines.append("None.")
    else:
        for row in repairs:
            lines.append(f"- id {row['id']}: {row.get('action')} — {row.get('reason')} — `{row.get('english', '')}`")
    lines += [
        "",
        "## Outputs",
        "",
    ]
    for key, value in (summary.get("outputs") or {}).items():
        lines.append(f"- {key}: `{value}`")
    lines += ["", "## Checks", ""]
    for row in summary.get("checks") or []:
        flag = "ok" if row["ok"] else "FAIL"
        lines.append(f"- [{flag}] {row['name']}: {row['detail']}")
    lines += [
        "",
        "## Limits",
        "",
        "- Timestamps are approximate Whisper times plus energy onset, not forced alignment.",
        "- A complete status means every segment was placed under the scheduling rules. It is not a listening approval.",
        "- This sample does not validate 1–2 hour recordings or a second unseen clip.",
        "",
    ]
    return "\n".join(lines)
