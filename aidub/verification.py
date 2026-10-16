"""Quality identities are separate from synthesis identities."""
from functools import lru_cache
from pathlib import Path
import inspect
import subprocess
import numpy as np
import soundfile as sf

from .asr_client import whisper_python
from .config import verification_model_file
from .quality import CHECKER_VERSION
from .util import fingerprint, sha256_file


@lru_cache(maxsize=16)
def _file_digest(path, size, mtime):
    return sha256_file(Path(path))


def file_identity(path: Path) -> dict:
    stat = path.stat()
    return {"sha256": _file_digest(str(path.resolve()), stat.st_size, (stat.st_mtime_ns, stat.st_ctime_ns)), "size": stat.st_size}


@lru_cache(maxsize=4)
def _whisper_version(python):
    result = subprocess.run([python, "-c", "import json; from importlib.metadata import version; print(json.dumps({n:version(n) for n in ('openai-whisper','torch','numpy')}))"],
                            capture_output=True, text=True, timeout=10)
    if result.returncode:
        raise RuntimeError(f"Cannot inspect Whisper environment {python}: {result.stderr[-1000:]}")
    return result.stdout.strip()


def verification_identity(cfg: dict, ref_sha: str) -> str:
    extra = {}
    if (cfg.get("quality") or {}).get("text_checker") or (cfg.get("voice_selection") or {}).get("enabled"):
        from .selection import pacing, pacing_issues
        extra = {"textnorm.py": sha256_file(Path(__file__).with_name("textnorm.py")),
                 "pacing_code": fingerprint([inspect.getsource(pacing), inspect.getsource(pacing_issues)])}
    return fingerprint({"assessment_schema": 1, "version": CHECKER_VERSION, "reference_sha256": ref_sha, **extra,
                        "pacing": assessment_pacing_settings(cfg), "waveform_environment": waveform_environment(),
                        "quality": cfg.get("quality") or {}, "asr_model": (cfg.get("quality") or {}).get("asr_model") or cfg["whisper"]["model"],
                        "asr_weights": file_identity(verification_model_file(cfg)),
                        "whisper_version": _whisper_version(whisper_python(cfg["executables"]["whisper"])),
                        "worker_version": sha256_file(Path(__file__).with_name("asr_worker.py")),
                        "checker_source": sha256_file(Path(__file__).with_name("quality.py")),
                        "audio_source": sha256_file(Path(__file__).with_name("audio.py"))})


def assessment_pacing_settings(cfg: dict) -> dict | None:
    from .selection import DEFAULTS, settings
    opts = settings(cfg)
    if not opts:
        return None
    return {**{k: opts[k] for k in ("pause_hard_sec", "reject_rate_low", "reject_rate_high")},
            "count_pause_soft_sec": DEFAULTS["pause_soft_sec"]}


def asr_request_settings(cfg: dict, second: bool = False) -> dict:
    language = (cfg.get("quality") or {}).get("asr_language") or ""
    options = None
    if (cfg.get("quality") or {}).get("text_checker") == "sequence-v1":
        options = {"condition_on_previous_text": False}
        if second:
            language = "en"
            options.update(beam_size=5, best_of=5, temperature=0.0)
    return {"language": language, "options": options,
            "word_timestamps": options is not None, "full_result": options is not None}


def hearing_identity(cfg: dict, device: str, second: bool = False) -> str:
    quality = cfg.get("quality") or {}
    return fingerprint({"schema": 1, "device": device,
                        "model": quality.get("asr_model") or cfg["whisper"]["model"],
                        "weights": file_identity(verification_model_file(cfg)),
                        "environment": _whisper_version(whisper_python(cfg["executables"]["whisper"])),
                        "worker": sha256_file(Path(__file__).with_name("asr_worker.py")),
                        "request": asr_request_settings(cfg, second)})


def waveform_identity(path: Path) -> str:
    return fingerprint({"waveform": file_identity(path), "schema": 1,
                        "environment": waveform_environment(),
                        "quality_source": sha256_file(Path(__file__).with_name("quality.py")),
                        "audio_source": sha256_file(Path(__file__).with_name("audio.py"))})


def waveform_environment() -> dict:
    # Waveform analysis runs in the coordinator, not necessarily Whisper's venv.
    return {"numpy": np.__version__, "soundfile": sf.__version__, "libsndfile": sf.__libsndfile_version__}


def verification_complete(quality: dict | None) -> bool:
    """Legacy first hearings remain evidence; known incomplete follow-ups never pass."""
    quality = quality or {}
    return bool(quality.get("verification_complete", True) and not quality.get("asr_skipped")
                and isinstance(quality.get("asr_text"), str)
                and (quality.get("second_verification") or {}).get("status") != "incomplete"
                and not (quality.get("second_verification") or {}).get("error"))


def candidate_quality_key(meta: dict, text: str, identity: str) -> str:
    return fingerprint({"verification": identity, "synthesis_cache_key": meta.get("cache_key"),
                        "waveform": sha256_file(Path(meta["path"])), "text": text})
