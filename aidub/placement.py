from dataclasses import dataclass


@dataclass
class Interval:
    seg_id: int
    start_sample: int
    end_sample: int


def collisions(intervals: list[Interval]) -> list[dict]:
    ordered = sorted(intervals, key=lambda x: (x.start_sample, x.seg_id))
    hits = []
    for i, a in enumerate(ordered):
        if a.end_sample <= a.start_sample:
            continue
        for b in ordered[i + 1:]:
            if b.start_sample >= a.end_sample:
                break
            if b.end_sample <= b.start_sample:
                continue
            ov_start = max(a.start_sample, b.start_sample)
            ov_end = min(a.end_sample, b.end_sample)
            if ov_end > ov_start:
                hits.append({
                    "id_a": a.seg_id,
                    "id_b": b.seg_id,
                    "start_sample": ov_start,
                    "end_sample": ov_end,
                    "overlap_samples": ov_end - ov_start,
                })
    return hits


def clamp_interval(start: int, n: int, n_frames: int) -> tuple[int, int, bool]:
    if n <= 0 or n_frames <= 0:
        return 0, 0, False
    if start < 0 or start >= n_frames:
        return start, 0, True
    end = start + n
    truncated = end > n_frames
    return start, min(end, n_frames) - start, truncated
