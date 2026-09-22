from pathlib import Path

import numpy as np

from .audio import read_audio, resample_audio, to_mono, write_wav
from .media import run_cmd
from .placement import Interval, clamp_interval, collisions


def mux_english_cmd(ffmpeg: str, video: str, mix_wav: str, dest: str) -> list[str]:
    return [
        ffmpeg, "-hide_banner", "-y",
        "-i", video,
        "-i", mix_wav,
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        "-metadata:s:a:0", "language=eng",
        "-disposition:a:0", "default",
        dest,
    ]


def mux_spanish_cmd(ffmpeg: str, video: str, mixed_ordinal: int, dest: str) -> list[str]:
    return [
        ffmpeg, "-hide_banner", "-y",
        "-i", video,
        "-map", "0:v:0",
        "-map", f"0:a:{int(mixed_ordinal)}",
        "-c", "copy",
        "-metadata:s:a:0", "language=spa",
        "-disposition:a:0", "default",
        dest,
    ]


def place_voice(scheduled: list[dict], n_frames: int, sr: int, fade_ms: float) -> tuple[np.ndarray, list[dict]]:
    mix = np.zeros(n_frames, dtype=np.float32)
    fade = int(round(fade_ms * sr / 1000.0))
    ordered = sorted(scheduled, key=lambda s: (float(s["start"]), int(s["id"])))
    limit = {}
    for i, item in enumerate(ordered):
        nxt = float(ordered[i + 1]["start"]) if i + 1 < len(ordered) else n_frames / sr
        limit[int(item["id"])] = int(round(nxt * sr))
    plans = []
    overlaps = []
    for item in scheduled:
        item["placement_start_sample"] = None
        item["placement_n_samples"] = 0
        if not item.get("placed"):
            continue
        path = Path(item["used_path"])
        wav, wav_sr = read_audio(path)
        mono = resample_audio(to_mono(wav), wav_sr, sr)
        start = int(round(float(item["placement_start"]) * sr))
        start, n, truncated = clamp_interval(start, int(mono.size), n_frames)
        if truncated and mono.size - n > 2:
            item["placed"] = False
            item["status"] = "unresolved"
            item["timing_error"] = (item.get("timing_error") or "") + "|would_truncate_past_eof"
            continue
        if n <= 0:
            item["placed"] = False
            item["status"] = "unresolved"
            item["timing_error"] = (item.get("timing_error") or "") + "|empty_placement"
            continue
        cap = limit.get(int(item["id"]), n_frames)
        if start + n > cap:
            overflow = start + n - cap
            if 0 < overflow <= 2 and cap - start > 0:
                n = cap - start
                item["sample_grid_trim"] = overflow
        piece = mono[:n].copy()
        if fade > 0 and n > 2 * fade:
            env = np.ones(n, dtype=np.float32)
            env[:fade] = np.linspace(0.0, 1.0, fade, dtype=np.float32)
            env[-fade:] = np.linspace(1.0, 0.0, fade, dtype=np.float32)
            piece *= env
        plans.append((item, start, piece))
    intervals = [Interval(item["id"], start, start + int(piece.size)) for item, start, piece in plans]
    hits = collisions(intervals)
    skip = {hit["id_b"] for hit in hits}
    overlaps = hits
    for item, start, piece in plans:
        if item["id"] in skip:
            item["placed"] = False
            item["status"] = "unresolved"
            item["timing_error"] = (item.get("timing_error") or "") + "|overlap_skipped_no_overwrite"
            continue
        mix[start:start + piece.size] = piece
        item["placement_start_sample"] = start
        item["placement_n_samples"] = int(piece.size)
        item["placement_end"] = (start + piece.size) / sr
        item["placed"] = True
    return mix, overlaps


def write_bilingual(path: Path, scheduled: list[dict]) -> None:
    lines = []
    for seg in scheduled:
        flag = "PLACED" if seg.get("placed") else "OMITTED"
        lines.append(f"[{seg['start']:.3f} - {seg['end']:.3f}] {seg.get('anchor_type', '')} {flag}")
        lines.append(f"ES: {seg.get('spanish', '')}")
        lines.append(f"EN: {seg.get('english', '')}")
        if seg.get("timing_error"):
            lines.append(f"ERROR: {seg['timing_error']}")
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def decode_ok(ffmpeg: str, path: str) -> tuple[bool, str]:
    proc = run_cmd_allow_fail([ffmpeg, "-v", "error", "-i", path, "-f", "null", "-"])
    err = (proc.stderr or "").strip()
    return proc.returncode == 0 and not err, err


def run_cmd_allow_fail(cmd: list[str]):
    import subprocess
    return subprocess.run(cmd, check=False, text=True, capture_output=True)
