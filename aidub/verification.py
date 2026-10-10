"""Quality identities are separate from synthesis identities."""
from functools import lru_cache
from pathlib import Path
import subprocess

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
        extra = {name: sha256_file(Path(__file__).with_name(name)) for name in ("textnorm.py", "selection.py")}
    return fingerprint({"version": CHECKER_VERSION, "reference_sha256": ref_sha, **extra,
                        "quality": cfg.get("quality") or {}, "asr_model": (cfg.get("quality") or {}).get("asr_model") or cfg["whisper"]["model"],
                        "asr_weights": file_identity(verification_model_file(cfg)),
                        "whisper_version": _whisper_version(whisper_python(cfg["executables"]["whisper"])),
                        "worker_version": sha256_file(Path(__file__).with_name("asr_worker.py")),
                        "checker_source": sha256_file(Path(__file__).with_name("quality.py")),
                        "audio_source": sha256_file(Path(__file__).with_name("audio.py"))})


def candidate_quality_key(meta: dict, text: str, identity: str) -> str:
    return fingerprint({"verification": identity, "synthesis_cache_key": meta.get("cache_key"),
                        "waveform": sha256_file(Path(meta["path"])), "text": text})
