from .util import fingerprint


def plan_fit(trim_dur: float, orig_avail: float, safe_window: float, max_tempo: float = 1.1, min_tempo: float = 1.0) -> tuple[str, float, str]:
    if trim_dur <= orig_avail + 1e-4:
        return "fit_unchanged", 1.0, ""
    if trim_dur <= safe_window + 1e-4:
        return "spill_into_gap", 1.0, ""
    needed = trim_dur / max(safe_window, 1e-6)
    if needed <= max_tempo + 1e-9:
        tempo = min(max_tempo, max(min_tempo, needed))
        return "needs_tempo", tempo, ""
    return "unresolved", 1.0, "overrun_tempo_limit"


def apply_blockers(status: str, timing_error: str, start: float, duration: float, occupied_until: float, source_duration: float) -> tuple[str, str]:
    if occupied_until > start + 1e-4:
        return "unresolved", timing_error or "blocked_by_previous"
    if start + duration > source_duration + 1e-4:
        return "unresolved", timing_error or "past_source_end"
    if duration > max(0.0, (source_duration - start)) + 1e-4 and status != "unresolved":
        return "unresolved", timing_error or "overlap_with_next"
    return status, timing_error


def synth_cache_key(text: str, reference_sha256: str, reference_text: str, seed: int, qwen: dict) -> str:
    return fingerprint({
        "text": text,
        "reference_sha256": reference_sha256,
        "reference_text": reference_text,
        "seed": int(seed),
        "model_id": qwen["model_id"],
        "attn_implementation": qwen["attn_implementation"],
        "dtype": qwen["dtype"],
        "language": qwen["language"],
        "x_vector_only_mode": qwen["x_vector_only_mode"],
        "generation": qwen["generation"],
    })


def primary_seed(seed_base: int, seg_id: int) -> int:
    return int(seed_base) + int(seg_id)


def alternate_seed(seed_base: int, seg_id: int, offset: int) -> int:
    return primary_seed(seed_base, seg_id) + int(offset)
