import subprocess
import tempfile
from pathlib import Path


def run_cmd(cmd: list[str], timeout: int | None = None) -> subprocess.CompletedProcess:
    if any(not isinstance(part, str) for part in cmd):
        raise TypeError("command arguments must be strings")
    with tempfile.TemporaryFile() as errors:
        try:
            proc = subprocess.run(cmd, check=False, text=True, stdout=subprocess.PIPE, stderr=errors, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"Media command exceeded {timeout}s; increase the applicable stage timeout and resume") from exc
        errors.seek(0, 2)
        size = errors.tell()
        errors.seek(max(0, size - 8000))
        detail = errors.read().decode("utf-8", "replace")
        if proc.returncode:
            raise RuntimeError(f"Media command failed ({proc.returncode}): {detail}")
        return subprocess.CompletedProcess(cmd, proc.returncode, proc.stdout, detail)


def probe_cmd(ffprobe: str, video: str) -> list[str]:
    return [
        ffprobe, "-hide_banner", "-print_format", "json",
        "-show_streams", "-show_format", video,
    ]


def probe(ffprobe: str, video: str, timeout: float = 1200) -> dict:
    proc = run_cmd(probe_cmd(ffprobe, video), timeout=timeout)
    import json
    doc = json.loads(proc.stdout)
    videos = [v for v in doc.get("streams", []) if v.get("codec_type") == "video"]
    if videos and videos[0].get("duration") in (None, "N/A"):
        try:
            doc["_aidub_video_timing"] = video_packet_span(ffprobe, video, timeout=timeout)
        except (RuntimeError, subprocess.SubprocessError) as exc:
            doc["_aidub_video_timing_error"] = str(exc)
    return doc


def _rate(value: str | None) -> float | None:
    if not value or value in {"0/0", "N/A"}:
        return None
    num, den = value.split("/")
    den_f = float(den)
    if den_f == 0:
        return None
    return float(num) / den_f


def _start_time(value) -> float:
    return 0.0 if value in (None, "N/A", "") else float(value)


def describe_streams(probe_doc: dict) -> dict:
    streams = probe_doc.get("streams") or []
    format_duration = (probe_doc.get("format") or {}).get("duration")
    if format_duration not in (None, "N/A"):
        format_duration = float(format_duration)
    else:
        format_duration = None
    videos = []
    audios = []
    for stream in streams:
        kind = stream.get("codec_type")
        if kind == "video":
            nb = stream.get("nb_frames")
            fps = _rate(stream.get("avg_frame_rate")) or _rate(stream.get("r_frame_rate"))
            duration = float(stream["duration"]) if stream.get("duration") not in (None, "N/A") else None
            nb_frames = int(nb) if nb and nb != "N/A" else None
            source, approximate = "stream", False
            start_time = _start_time(stream.get("start_time"))
            timing = probe_doc.get("_aidub_video_timing") or {}
            if duration is None and timing:
                start_time = float(stream["start_time"]) if stream.get("start_time") not in (None, "N/A") else timing["start"]
                duration = timing["end"] - start_time
                source, approximate = "video_packet_timestamps", timing.get("approximate", False)
            if duration is None and nb_frames and fps:
                duration = nb_frames / fps
                source, approximate = "frames_divided_by_fps", True
            if duration is None and format_duration is not None:
                duration = _start_time((probe_doc.get("format") or {}).get("start_time")) + format_duration - start_time
                source, approximate = "container_fallback", True
            videos.append({
                "absolute_index": int(stream["index"]),
                "codec_name": stream.get("codec_name"),
                "width": stream.get("width"),
                "height": stream.get("height"),
                "avg_frame_rate": stream.get("avg_frame_rate"),
                "fps": fps,
                "nb_frames": nb_frames,
                "duration": duration,
                "duration_source": source,
                "duration_approximate": approximate,
                "start_time": start_time,
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
                "start_time": _start_time(stream.get("start_time")),
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


def bitstream_md5(ffmpeg: str, path: str, timeout: float = 10800) -> str:
    proc = run_cmd([ffmpeg, "-v", "error", "-i", path, "-map", "0:v:0", "-c", "copy", "-f", "md5", "-"], timeout=timeout)
    text = (proc.stdout or "") + "\n" + (proc.stderr or "")
    for line in text.splitlines():
        if "MD5=" in line:
            return line.strip().split("MD5=")[-1].strip()
    raise RuntimeError(f"Could not hash the video bitstream of {path}: {text[-500:]}")


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


def video_packet_span(ffprobe: str, path: str, *, timeout: float = 1200) -> dict:
    """Scan video-only packet timestamps with file-backed stdout, bounded RAM."""
    import tempfile
    with tempfile.TemporaryFile() as output:
        proc = subprocess.run([ffprobe, "-v", "error", "-select_streams", "v:0", "-show_packets",
                               "-show_entries", "packet=pts_time,dts_time,duration_time", "-of", "compact=p=0", path],
                              stdout=output, stderr=subprocess.PIPE, timeout=timeout)
        if proc.returncode:
            raise RuntimeError(f"Video timestamp probe failed: {proc.stderr.decode(errors='replace')[-1000:]}")
        output.seek(0)
        first, end, last_duration, last_start, previous = None, None, None, None, None
        for line in output:
            fields = dict(part.split("=", 1) for part in line.decode().strip().split("|") if "=" in part)
            timestamp = fields.get("pts_time") or fields.get("dts_time")
            if timestamp in (None, "N/A"):
                timestamp = fields.get("dts_time")
            if timestamp in (None, "N/A"):
                continue
            start = float(timestamp)
            duration = float(fields["duration_time"]) if fields.get("duration_time") not in (None, "N/A") else 0.0
            first = start if first is None else min(first, start)
            if last_start is None or start > last_start:
                if last_start is not None:
                    previous = last_start
                last_start, last_duration = start, duration
            finish = start + duration
            end = finish if end is None else max(end, finish)
        if first is None or end is None:
            raise RuntimeError("Video packets have no usable timestamps")
        approximate = not last_duration or last_duration <= 0
        if approximate and previous is not None:
            end = max(end, last_start + last_start - previous)
        if end <= first:
            raise RuntimeError("Cannot establish a positive video duration")
        return {"start": first, "end": end, "approximate": approximate}


def validate_container(described: dict, mixed_ordinal: int, container: str = "mp4") -> None:
    if container not in {"mp4", "mkv"}:
        raise RuntimeError("export.container must be mp4 or mkv")
    if container == "mp4":
        video = described["video"]["codec_name"]
        audio = resolve_ordinal(described, mixed_ordinal, "mixed")["codec_name"]
        if video not in {"h264", "hevc", "av1", "mpeg4"} or audio not in {"aac", "mp3", "ac3", "eac3", "alac"}:
            raise RuntimeError(f"Cannot safely stream-copy {video}/{audio} to the supported MP4 output. "
                               "Set export.container=mkv or provide compatible source streams; picture re-encoding is refused.")


def frame_check(source: dict, output: dict) -> dict:
    a, b = source.get("nb_frames"), output.get("nb_frames")
    if a is None or b is None:
        return {"ok": None, "status": "unavailable", "required": False,
                "detail": f"source={a}, output={b}; require the separate video bitstream identity check"}
    return {"ok": a == b, "status": "passed" if a == b else "failed", "required": True, "detail": f"{b} vs {a}"}


def encoded_audio_metrics(ffmpeg: str, path: str, *, block_frames: int = 65536, timeout: float = 10800) -> dict:
    """Measure decoded export audio using bounded pipe reads; never decode picture."""
    import os
    import select
    import time
    import numpy as np
    metrics = {"peak": 0.0, "samples": 0, "over_full_scale_samples": 0, "finite": True}
    with tempfile.TemporaryFile() as errors:
        proc = subprocess.Popen([ffmpeg, "-v", "error", "-i", path, "-map", "0:a:0", "-vn",
                                 "-ac", "2", "-c:a", "pcm_f32le", "-f", "f32le", "-"],
                                stdout=subprocess.PIPE, stderr=errors)
        poller = select.poll()
        poller.register(proc.stdout, select.POLLIN | select.POLLHUP)
        deadline = time.monotonic() + timeout
        pending = b""
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError(f"Encoded audio validation exceeded {timeout}s")
                if not poller.poll(min(1000, max(1, int(remaining * 1000)))):
                    continue
                data = os.read(proc.stdout.fileno(), block_frames * 8)
                if not data:
                    break
                pending += data
                usable = len(pending) // 8 * 8
                audio = np.frombuffer(pending[:usable], dtype='<f4')
                if audio.size:
                    metrics['peak'] = max(metrics['peak'], float(np.max(np.abs(audio))))
                    metrics['samples'] += audio.size
                    metrics['finite'] = metrics['finite'] and bool(np.isfinite(audio).all())
                    metrics['over_full_scale_samples'] += int(np.count_nonzero(np.abs(audio) >= 1.0))
                pending = pending[usable:]
            proc.wait(timeout=max(0.1, deadline - time.monotonic()))
            errors.seek(0, 2)
            size = errors.tell(); errors.seek(max(0, size - 8000))
            if proc.returncode or pending or size or not metrics['samples']:
                raise RuntimeError(f"Export audio decode failed: {errors.read().decode(errors='replace')}")
            return metrics
        finally:
            if proc.poll() is None:
                proc.kill(); proc.wait(timeout=5)
            proc.stdout.close()
