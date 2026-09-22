import subprocess
from pathlib import Path


def run_cmd(cmd: list[str], timeout: int | None = None) -> subprocess.CompletedProcess:
    if any(not isinstance(part, str) for part in cmd):
        raise TypeError("command arguments must be strings")
    return subprocess.run(cmd, check=True, text=True, capture_output=True, timeout=timeout)


def probe_cmd(ffprobe: str, video: str) -> list[str]:
    return [
        ffprobe, "-hide_banner", "-print_format", "json",
        "-show_streams", "-show_format", video,
    ]


def probe(ffprobe: str, video: str) -> dict:
    proc = run_cmd(probe_cmd(ffprobe, video))
    import json
    return json.loads(proc.stdout)


def _rate(value: str | None) -> float | None:
    if not value or value in {"0/0", "N/A"}:
        return None
    num, den = value.split("/")
    den_f = float(den)
    if den_f == 0:
        return None
    return float(num) / den_f


def describe_streams(probe_doc: dict) -> dict:
    streams = probe_doc.get("streams") or []
    videos = []
    audios = []
    for stream in streams:
        kind = stream.get("codec_type")
        if kind == "video" and not videos:
            nb = stream.get("nb_frames")
            fps = _rate(stream.get("avg_frame_rate")) or _rate(stream.get("r_frame_rate"))
            duration = float(stream["duration"]) if stream.get("duration") not in (None, "N/A") else None
            nb_frames = int(nb) if nb and nb != "N/A" else None
            if duration is None and nb_frames and fps:
                duration = nb_frames / fps
            videos.append({
                "absolute_index": int(stream["index"]),
                "codec_name": stream.get("codec_name"),
                "width": stream.get("width"),
                "height": stream.get("height"),
                "avg_frame_rate": stream.get("avg_frame_rate"),
                "fps": fps,
                "nb_frames": nb_frames,
                "duration": duration,
                "start_time": float(stream.get("start_time") or 0.0),
                "time_base": stream.get("time_base"),
            })
        elif kind == "audio":
            audios.append({
                "audio_ordinal": len(audios),
                "absolute_index": int(stream["index"]),
                "codec_name": stream.get("codec_name"),
                "sample_rate": int(stream["sample_rate"]) if stream.get("sample_rate") else None,
                "channels": stream.get("channels"),
                "channel_layout": stream.get("channel_layout"),
                "start_time": float(stream.get("start_time") or 0.0),
                "duration": float(stream["duration"]) if stream.get("duration") not in (None, "N/A") else None,
                "time_base": stream.get("time_base"),
                "tags": stream.get("tags") or {},
                "disposition": stream.get("disposition") or {},
            })
    if len(videos) != 1:
        raise RuntimeError(f"Expected one video stream, found {len(videos)}")
    return {"video": videos[0], "audios": audios, "format": probe_doc.get("format") or {}}


def resolve_ordinal(described: dict, ordinal: int, role: str) -> dict:
    audios = described["audios"]
    if ordinal < 0 or ordinal >= len(audios):
        raise RuntimeError(
            f"{role} audio ordinal {ordinal} is out of range. This file has {len(audios)} audio streams. "
            "Ordinals are not absolute container indices."
        )
    chosen = audios[ordinal]
    if chosen["audio_ordinal"] != ordinal:
        raise RuntimeError("Internal ordinal mismatch")
    return chosen


def extract_audio_cmd(ffmpeg: str, video: str, ordinal: int, dest: str, sample_rate: int = 48000) -> list[str]:
    return [
        ffmpeg, "-hide_banner", "-y",
        "-i", video,
        "-map", f"0:a:{int(ordinal)}",
        "-c:a", "pcm_s16le",
        "-ar", str(sample_rate),
        dest,
    ]


def assert_extract_preserves_origin(cmd: list[str]) -> None:
    banned = {"-ss", "-sseof", "-itsoffset", "aresetpts", "asetpts"}
    for part in cmd:
        if part in banned or any(tok in part for tok in ("aresetpts", "asetpts")):
            raise RuntimeError(f"Extract command would move stream origin: {cmd}")


def align_to_video(wav, sample_rate: int, audio_start: float, video_start: float, video_duration: float):
    import numpy as np

    offset = float(audio_start) - float(video_start)
    if offset < -1e-4:
        raise RuntimeError(
            f"Audio start {audio_start} is before video start {video_start}. "
            "Refusing to shift origins independently."
        )
    lead = int(round(offset * sample_rate))
    total = int(round(float(video_duration) * sample_rate))
    if wav.ndim == 1:
        wav = wav[:, None]
    out = np.zeros((total, wav.shape[1]), dtype=np.float32)
    end = lead + wav.shape[0]
    truncated = 0
    usable = wav
    if end > total:
        keep = max(0, total - lead)
        truncated = int(wav.shape[0] - keep)
        usable = wav[:keep]
        end = lead + usable.shape[0]
    if lead >= total:
        raise RuntimeError("Audio offset is past the video endpoint.")
    out[lead:end] = usable
    return out, {"lead_samples": lead, "tail_samples": int(total - end), "truncated_samples": truncated, "total_samples": total}
