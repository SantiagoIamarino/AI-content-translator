"""Bounded per-line synthesis, quality retries, and fit attempts."""

from __future__ import annotations

from .schedule import alternate_seed, primary_seed


def revision_limit(cfg: dict) -> int:
    repair = cfg.get("repair") or {}
    manual = int(repair.get("max_compact_revisions", 1))
    unattended = cfg.get("unattended") or {}
    if unattended.get("enabled"):
        return int(unattended.get("max_shorter_translations", manual))
    return manual


def quality_seed_sequence(primary: int, max_retries: int) -> list[int]:
    return [int(primary) + 1000 * i for i in range(int(max_retries) + 1)]


def alternate_seed_sequence(primary: int, step: int, count: int) -> list[int]:
    return [int(primary) + int(step) * (i + 1) for i in range(int(count))]


def leading_shift(start: float, duration: float, occupied_until: float, next_start: float, max_shift: float) -> float:
    """Move this line earlier into silence that the previous line did not use.

    Later lines stay where they are. A zero result means the shift is not available.
    """
    overflow = (float(start) + float(duration)) - float(next_start)
    if overflow <= 1e-3:
        return 0.0
    room = max(0.0, float(start) - float(occupied_until))
    shift = min(room, overflow, max(0.0, float(max_shift)))
    if shift > 0.02 and (float(start) - shift + float(duration)) <= float(next_start) + 1e-4:
        return float(shift)
    return 0.0


def account_lines(segment_ids: list[int], placed_ids: list[int], unresolved_ids: list[int]) -> list[int]:
    """Ids that are neither placed nor explicitly unresolved."""
    placed = set(placed_ids)
    unresolved = set(unresolved_ids)
    return [int(i) for i in segment_ids if int(i) not in placed and int(i) not in unresolved]


def _candidate_quality(attempt, quality, seg=None, cfg=None):
    if seg is not None and cfg is not None:
        from .performance import contextual_quality
        quality = contextual_quality(attempt, quality, seg, cfg.get("voice_selection") or {})
    if attempt.get("presentation_rejected"):
        attempt["raw_quality"] = quality
        return dict(quality, ok=False, reasons=list(quality.get("reasons") or []) + [attempt["presentation_rejected"]])
    return quality


def _quality_failure(attempt: dict) -> dict:
    chosen = dict(attempt)
    chosen["placed"] = False
    chosen["status"] = "unresolved"
    reasons = (attempt.get("quality") or {}).get("reasons") or ["quality_rejected"]
    chosen["timing_error"] = "quality_rejected:" + ",".join(reasons)
    return chosen


def collect_line(
    seg: dict,
    *,
    occupied: float,
    next_start: float,
    source_duration: float,
    cfg: dict,
    synthesize,
    assess,
    attempt_fn,
    revision_limit_n: int,
) -> dict:
    """Try quality seeds, then fit seeds, then leading silence. Do not move later lines."""
    if any(r.get("action") == "leave_unresolved" for r in seg.get("revisions") or []):
        return {"skip": "leave_unresolved", "attempts": [], "needs_repair": False, "chosen": None}
    text = seg["english"]
    primary = primary_seed(cfg["schedule"]["seed_base"], seg["id"])
    max_q = int((cfg.get("quality") or {}).get("max_retries", 2))
    max_alt = int((cfg.get("fit_retries") or {}).get("max_alternate_seeds", 3))
    max_shift = float((cfg.get("fit_retries") or {}).get("max_leading_shift_sec", 0.4))
    step = int(cfg["schedule"]["alternate_seed_offset"])
    base_kind = "compact_revision" if seg.get("revisions") else "primary"
    attempts = []
    chosen = None
    for index, seed in enumerate(quality_seed_sequence(primary, max_q)):
        meta = synthesize(text, seed)
        quality = assess(meta, text)
        kind = base_kind if index == 0 else "quality_retry"
        attempt = attempt_fn(seg, text, seed, kind, meta, occupied, next_start, source_duration)
        quality = _candidate_quality(attempt, quality, seg, cfg)
        attempt["quality"] = quality
        attempts.append(attempt)
        if quality.get("ok"):
            chosen = attempt
            break
    if chosen is None:
        failed = _quality_failure(attempts[-1] if attempts else {"quality": {"reasons": ["quality_rejected"]}})
        return {"chosen": failed, "attempts": attempts, "needs_repair": False, "skip": None}

    if (not chosen["placed"]) and (not seg.get("revisions")):
        for seed in alternate_seed_sequence(primary, step, max_alt):
            meta = synthesize(text, seed)
            quality = assess(meta, text)
            attempt = attempt_fn(seg, text, seed, "alternate_seed", meta, occupied, next_start, source_duration)
            quality = _candidate_quality(attempt, quality, seg, cfg)
            attempt["quality"] = quality
            attempts.append(attempt)
            if not quality.get("ok"):
                continue
            shorter = float(attempt["trim_duration_sec"]) < float(chosen["trim_duration_sec"])
            if attempt["placed"] or shorter:
                chosen = attempt
            if attempt["placed"]:
                break

    if not chosen["placed"] and (chosen.get("quality") or {}).get("ok"):
        shift = leading_shift(
            float(seg["start"]),
            float(chosen["generated_duration_sec"]),
            occupied,
            next_start,
            max_shift,
        )
        if shift > 0:
            chosen = dict(chosen)
            chosen["placement_start"] = float(seg["start"]) - shift
            chosen["placed"] = True
            chosen["status"] = "spill_into_leading_silence"
            chosen["timing_error"] = ""
            chosen["leading_shift_sec"] = shift

    revisions = seg.get("revisions") or []
    needs_repair = (
        (not chosen["placed"])
        and bool((chosen.get("quality") or {}).get("ok"))
        and len(revisions) < int(revision_limit_n)
        and not any(r.get("action") == "leave_unresolved" for r in revisions)
    )
    return {"chosen": chosen, "attempts": attempts, "needs_repair": needs_repair, "skip": None}


def collect_line_best_of_n(
    seg: dict,
    *,
    occupied: float,
    next_start: float,
    source_duration: float,
    cfg: dict,
    synthesize,
    assess,
    attempt_fn,
    revision_limit_n: int,
    score,
    candidates: int,
    max_extra: int,
    search_for_placeable: bool = False,
) -> dict:
    """Generate N valid takes (extra seeds replace failures), score every valid take, then choose.

    Placeable takes are preferred; among them the lowest evidence score wins.
    """
    revisions = seg.get("revisions") or []
    if any(r.get("action") == "leave_unresolved" for r in revisions):
        return {"skip": "leave_unresolved", "attempts": [], "needs_repair": False, "chosen": None}
    text = seg["english"]
    primary = primary_seed(cfg["schedule"]["seed_base"], seg["id"])
    base_kind = "compact_revision" if revisions else "primary"
    attempts, valid = [], []
    budget = int(candidates) + int(max_extra)
    for index in range(budget):
        if len(valid) >= int(candidates) and (not search_for_placeable or any(a.get("placed") for a in valid)):
            break
        seed = int(primary) + 1000 * index
        meta = synthesize(text, seed)
        quality = assess(meta, text)
        kind = base_kind if index == 0 else "candidate"
        attempt = attempt_fn(seg, text, seed, kind, meta, occupied, next_start, source_duration)
        quality = _candidate_quality(attempt, quality, seg, cfg)
        attempt["quality"] = quality
        attempts.append(attempt)
        if quality.get("ok"):
            attempt["selection"] = score(attempt)
            valid.append(attempt)
    summary = {"generated": len(attempts), "valid": len(valid), "requested": int(candidates)}
    if not valid:
        failed = _quality_failure(attempts[-1] if attempts else {"quality": {"reasons": ["quality_rejected"]}})
        failed["selection_summary"] = summary
        return {"chosen": failed, "attempts": attempts, "needs_repair": False, "skip": None}
    from .selection import choose
    chosen = dict(choose(valid))
    if not chosen["placed"] and seg.get("anchor_type") != "vocal_event" and not seg.get("required_event_prefix"):
        shortest = min(valid, key=lambda a: float(a["generated_duration_sec"]))
        shift = leading_shift(float(seg["start"]), float(shortest["generated_duration_sec"]), occupied, next_start,
                              float((cfg.get("fit_retries") or {}).get("max_leading_shift_sec", 0.4)))
        if shift > 0:
            chosen = dict(shortest)
            chosen["placement_start"] = float(seg["start"]) - shift
            chosen["placed"] = True
            chosen["status"] = "spill_into_leading_silence"
            chosen["timing_error"] = ""
            chosen["leading_shift_sec"] = shift
    ranked = sorted(valid, key=lambda a: a["selection"]["score"])
    summary["chosen"] = dict(chosen["selection"], seed=chosen["seed"], kind=chosen["kind"])
    summary["ranking"] = [{"seed": a["seed"], "score": a["selection"]["score"], "placed": a["placed"],
                           "tempo": a.get("tempo")} for a in ranked]
    summary["margin_to_next"] = round(ranked[1]["selection"]["score"] - ranked[0]["selection"]["score"], 4) if len(ranked) > 1 else None
    chosen["selection_summary"] = summary
    needs_repair = (not chosen["placed"]) and len(revisions) < int(revision_limit_n) and seg.get("anchor_type") != "vocal_event" and not seg.get("required_event_prefix")
    return {"chosen": chosen, "attempts": attempts, "needs_repair": needs_repair, "skip": None}


def seed_is_alternate(seed_base: int, seg_id: int, offset: int, seed: int) -> bool:
    return int(seed) == alternate_seed(seed_base, seg_id, offset)
