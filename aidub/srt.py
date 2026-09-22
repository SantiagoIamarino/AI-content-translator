def fmt_srt(t: float) -> str:
    if t < 0:
        t = 0.0
    ms = int(round(t * 1000.0))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def render_srt(scheduled: list[dict]) -> str:
    blocks = []
    n = 1
    for seg in scheduled:
        if not seg.get("placed"):
            continue
        start = float(seg["placement_start"])
        end = float(seg["placement_end"])
        text = str(seg.get("english") or "").strip()
        if not text or end <= start:
            continue
        blocks.append(f"{n}\n{fmt_srt(start)} --> {fmt_srt(end)}\n{text}\n")
        n += 1
    return "\n".join(blocks) + ("\n" if blocks else "")


def omitted_lines(scheduled: list[dict]) -> list[dict]:
    rows = []
    for seg in scheduled:
        if seg.get("placed"):
            continue
        rows.append({
            "id": seg["id"],
            "english": seg.get("english"),
            "spanish": seg.get("spanish"),
            "status": seg.get("status"),
            "timing_error": seg.get("timing_error") or "",
        })
    return rows
