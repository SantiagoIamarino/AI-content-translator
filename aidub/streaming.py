"""Full recording audio stays on disk. Work is bounded by a block and one cue."""
from __future__ import annotations

import os
from pathlib import Path
import numpy as np
import soundfile as sf

from .audio import read_audio, resample_audio, to_mono, voice_gain_bound


def block_frames(cfg: dict) -> int:
    n = int((cfg.get("processing") or {}).get("block_frames", 65536))
    if not 128 <= n <= 1048576:
        raise RuntimeError("processing.block_frames must be between 128 and 1048576")
    return n


def alignment_meta(frames, sr, audio_start, video_start, duration):
    offset = float(audio_start) - float(video_start)
    if offset < -1e-4:
        raise RuntimeError("Audio starts before video; independent timestamp shifts are refused")
    lead, total = int(round(offset * sr)), int(round(duration * sr))
    if lead >= total:
        raise RuntimeError("Audio offset is past the video endpoint")
    end = lead + frames
    return {"lead_samples": lead, "total_samples": total,
            "tail_samples": max(0, total - end), "truncated_samples": max(0, end - total)}


class AlignedGame:
    def __init__(self, path, sr, meta):
        self.handle = sf.SoundFile(path)
        if self.handle.samplerate != sr or self.handle.channels != 2:
            self.handle.close()
            raise RuntimeError("Game audio must remain stereo at output_sr")
        if meta["truncated_samples"]:
            self.handle.close()
            raise RuntimeError("Game audio extends past the video; truncation is refused")
        self.meta = meta

    def read(self, start, count):
        out = np.zeros((count, 2), dtype=np.float32)
        lo = max(start, self.meta["lead_samples"])
        hi = min(start + count, self.meta["lead_samples"] + self.handle.frames)
        if hi > lo:
            self.handle.seek(lo - self.meta["lead_samples"])
            out[lo - start:hi - start] = self.handle.read(hi - lo, dtype="float32", always_2d=True)
        return out

    def close(self):
        self.handle.close()


def cue_audio(item, sr, fade_ms):
    audio, rate = read_audio(Path(item["used_path"]))
    mono = resample_audio(to_mono(audio), rate, sr).copy()
    fade = int(round(fade_ms * sr / 1000))
    if fade and mono.size > 2 * fade:
        mono[:fade] *= np.linspace(0, 1, fade, dtype=np.float32)
        mono[-fade:] *= np.linspace(1, 0, fade, dtype=np.float32)
    return mono


def stream_mix(game_path: Path, scheduled: list[dict], out_dir: Path, sr: int, meta: dict,
               cfg: dict, fade_ms: float = 0) -> dict:
    n_block = block_frames(cfg)
    ceiling = float(cfg["mix"]["limiter"])
    min_gain = float(cfg["mix"].get("min_voice_gain", 0.1))
    policy = cfg["mix"].get("headroom_policy", "partial")
    if policy not in {"partial", "fail"} or not 0 <= min_gain <= 1 or not 0 < ceiling < 1:
        raise RuntimeError("mix requires headroom_policy partial/fail, min_voice_gain 0..1, and limiter 0..1")
    out_dir.mkdir(parents=True, exist_ok=True)
    total = meta["total_samples"]
    game = AlignedGame(game_path, sr, meta)
    plans, occupied, before_peak = [], 0, 0.0
    ordered = sorted(scheduled, key=lambda r: (r["start"], r["id"]))
    try:
        for i, item in enumerate(ordered):
            if not item.get("placed"):
                continue
            audio = cue_audio(item, sr, fade_ms)
            start = int(round(item["placement_start"] * sr))
            next_start = int(round(ordered[i + 1]["start"] * sr)) if i + 1 < len(ordered) else total
            available = min(total, next_start) - start
            if start < 0 or start < occupied or available <= 0 or len(audio) > available + 2:
                item.update(placed=False, status="unresolved", timing_error="assembler_window_or_overlap")
                continue
            audio = audio[:available]
            gain = 1.0
            for pos in range(0, len(audio), n_block):
                voice = audio[pos:pos + n_block]
                bed = game.read(start + pos, len(voice))
                gain = min(gain, voice_gain_bound(bed, voice, ceiling))
                before_peak = max(before_peak, float(np.max(np.abs(bed + voice[:, None]))))
            if gain < min_gain or (gain == 0 and np.any(audio)):
                item.update(placed=False, status="unresolved", timing_error="insufficient_game_headroom",
                            voice_gain=gain)
                continue
            item.update(voice_gain=gain, placement_start_sample=start, placement_n_samples=len(audio),
                        placement_end=(start + len(audio)) / sr)
            plans.append(item)
            occupied = start + len(audio)
        suffix = f".{os.getpid()}.tmp.wav"
        voice_tmp = out_dir / ("english_voice" + suffix)
        mix_tmp = out_dir / ("english_mix" + suffix)
        info = {"gain": 1.0, "game_gain": 1.0, "game_peak": 0.0, "voice_peak": 0.0,
                "sum_peak_before_gain": before_peak, "mix_peak": 0.0, "clipping_samples": 0,
                "source_clipping_samples": 0, "source_over_ceiling_samples": 0,
                "voice_gains": {str(r["id"]): r["voice_gain"] for r in plans},
                "aligned_frames": total, "block_frames": n_block, "headroom_policy": policy,
                "voice_placement": "actual voice after cue gain copied to L and R"}
        cursor, active, active_audio = 0, None, None
        with sf.SoundFile(voice_tmp, "w", samplerate=sr, channels=1, subtype="FLOAT", format="WAV") as vf, \
             sf.SoundFile(mix_tmp, "w", samplerate=sr, channels=2, subtype="FLOAT", format="WAV") as mf:
            for start in range(0, total, n_block):
                count = min(n_block, total - start)
                voice = np.zeros(count, dtype=np.float32)
                while cursor < len(plans):
                    item = plans[cursor]
                    cue_start, cue_end = item["placement_start_sample"], item["placement_start_sample"] + item["placement_n_samples"]
                    if cue_start >= start + count:
                        break
                    if active is not item:
                        active, active_audio = item, cue_audio(item, sr, fade_ms)[:item["placement_n_samples"]] * item["voice_gain"]
                    lo, hi = max(start, cue_start), min(start + count, cue_end)
                    voice[lo - start:hi - start] = active_audio[lo - cue_start:hi - cue_start]
                    if cue_end > start + count:
                        break
                    cursor += 1
                    active, active_audio = None, None
                bed = game.read(start, count)
                mixed = bed + voice[:, None]
                if not np.isfinite(mixed).all():
                    raise RuntimeError("Non-finite game/voice mix")
                info["game_peak"] = max(info["game_peak"], float(np.max(np.abs(bed))))
                info["voice_peak"] = max(info["voice_peak"], float(np.max(np.abs(voice))))
                info["mix_peak"] = max(info["mix_peak"], float(np.max(np.abs(mixed))))
                info["source_over_ceiling_samples"] += int(np.count_nonzero(np.abs(bed) > ceiling))
                info["source_clipping_samples"] += int(np.count_nonzero(np.abs(bed) >= 0.999))
                info["clipping_samples"] += int(np.count_nonzero((np.abs(mixed) >= 0.999) & (np.abs(bed) < 0.999)))
                vf.write(voice)
                mf.write(mixed)
        info["source_headroom_ok"] = info["source_over_ceiling_samples"] == 0
        if not info["source_headroom_ok"] and policy == "fail":
            raise RuntimeError("Source game exceeds the configured ceiling. Game preserved; temporary output retained. Choose explicit partial policy.")
        os.replace(voice_tmp, out_dir / "english_voice.wav")
        os.replace(mix_tmp, out_dir / "english_mix.wav")
        return info
    finally:
        game.close()


def validate_audio_files(game_path, voice_path, mix_path, sr, meta, cfg):
    game = AlignedGame(game_path, sr, meta)
    error, peak, frames = 0.0, 0.0, 0
    try:
        with sf.SoundFile(voice_path) as vf, sf.SoundFile(mix_path) as mf:
            shape_ok = (vf.samplerate == mf.samplerate == sr and vf.frames == mf.frames == meta["total_samples"]
                        and vf.channels == 1 and mf.channels == 2)
            for start in range(0, min(vf.frames, mf.frames), block_frames(cfg)):
                count = min(block_frames(cfg), vf.frames - start, mf.frames - start)
                v = vf.read(count, dtype="float32", always_2d=True)
                m = mf.read(count, dtype="float32", always_2d=True)
                bed = game.read(start, count)
                error = max(error, float(np.max(np.abs(m - (bed + v)))))
                peak = max(peak, float(np.max(np.abs(m))))
                frames += count
            return {"shape_ok": shape_ok, "frames": frames, "game_bed_error": error, "mix_peak": peak}
    finally:
        game.close()
