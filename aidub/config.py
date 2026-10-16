import os
import copy
import shutil
import subprocess
from pathlib import Path

from .util import read_json, sha256_bytes

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIRMED_REFERENCE_TEXT = (
    "okay so uh we have this kind of dogs i don't know they're coming from the church "
    "i guess okay they almost hit me okay shouldn't oh he bite me i'm gonna try to use "
    "the shotgun this time try to shotgun him there you go there you go another one"
)


def spanish_comparison_enabled(cfg: dict) -> bool:
    """Missing means legacy-on; new snapshots materialize an explicit default."""
    value = (cfg.get("export") or {}).get("spanish_compare", True)
    if not isinstance(value, bool):
        raise ValueError("export.spanish_compare must be true or false")
    return value


def new_job_config(cfg: dict) -> dict:
    result = copy.deepcopy(cfg)
    result.setdefault("export", {}).setdefault("spanish_compare", False)
    spanish_comparison_enabled(result)
    return result


def load_config(path: Path | None = None) -> dict:
    cfg_path = path or (Path(os.environ["AIDUB_CONFIG"]) if os.environ.get("AIDUB_CONFIG") else
                        PROJECT_ROOT / "config" / "local.json" if (PROJECT_ROOT / "config/local.json").is_file() else
                        PROJECT_ROOT / "config" / "default.json")
    cfg_path = Path(cfg_path).expanduser()
    cfg = read_json(cfg_path)
    cfg["_config_path"] = str(cfg_path.resolve())
    cfg["_project_root"] = str(PROJECT_ROOT)
    return cfg


def resolve_path(cfg: dict, value: str) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return Path(cfg["_project_root"]) / path


def reference_text(cfg: dict) -> str:
    path = resolve_path(cfg, cfg["reference"]["text_file"])
    text = path.read_text(encoding="utf-8").strip()
    return text


def jobs_dir(cfg: dict) -> Path:
    return resolve_path(cfg, cfg["jobs_dir"])


def require_schedule_defaults(cfg: dict) -> None:
    sch = cfg["schedule"]
    if float(sch["trim_rms"]) != 0.005 or float(sch["trim_window_sec"]) != 0.01:
        raise RuntimeError("Refusing to change the validated trim RMS 0.005 / 10 ms window.")
    if int(sch["trim_pad_ms"]) != 0:
        raise RuntimeError("Qwen scheduling uses trim pad 0 ms. Refusing a different pad.")
    if float(sch["max_tempo"]) != 1.1:
        raise RuntimeError("Refusing to change max tempo from 1.10.")
    q = cfg["qwen3"]
    if q["model_id"] != "Qwen/Qwen3-TTS-12Hz-1.7B-Base":
        raise RuntimeError("Refusing a different TTS model.")
    if q["attn_implementation"] != "sdpa" or q["dtype"] != "bfloat16":
        raise RuntimeError("Refusing to change Qwen dtype or attention.")
    if q["language"] != "English" or q["x_vector_only_mode"] is not False:
        raise RuntimeError("Qwen must stay English ICL with x_vector_only_mode false.")
    expected_hash = cfg["reference"].get("expected_text_sha256")
    matches = sha256_bytes(reference_text(cfg).encode()) == expected_hash if expected_hash else reference_text(cfg) == CONFIRMED_REFERENCE_TEXT
    if not matches:
        raise RuntimeError("Reference transcript does not match the user-confirmed text.")


def executable(cfg: dict, key: str) -> str:
    value = cfg["executables"].get(key) or ""
    path = shutil.which(value) if "/" not in value else str(resolve_path(cfg, value))
    if not path or not Path(path).is_file() or not os.access(path, os.X_OK):
        raise RuntimeError(f"Missing executable {key}: {value!r}. Set executables.{key} in your local config.")
    return path


def whisper_model_file(cfg: dict) -> Path:
    explicit = (cfg.get("models") or {}).get("whisper_path")
    if explicit:
        path = resolve_path(cfg, explicit)
    else:
        model = cfg["whisper"]["model"]
        if Path(model).is_file():
            path = Path(model)
        else:
            name = {"turbo": "large-v3-turbo", "large": "large-v3"}.get(model, model)
            root = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))) / "whisper"
            path = root / f"{name}.pt"
    if not path.is_file():
        raise RuntimeError(f"Missing local Whisper weights: {path}. Configure models.whisper_path; aidub will not download them.")
    return path


def qwen_snapshot(cfg: dict) -> str:
    explicit = (cfg.get("models") or {}).get("qwen_path")
    if explicit:
        path = resolve_path(cfg, explicit)
    else:
        from .synth import resolve_local_snapshot
        path = Path(resolve_local_snapshot(cfg["qwen3"]["model_id"]))
    index = path / "model.safetensors.index.json"
    weights = [path / p for p in set(read_json(index).get("weight_map", {}).values())] if index.is_file() else [path / "model.safetensors"]
    if not (path / "config.json").is_file() or not weights or not all(p.is_file() and p.stat().st_size for p in weights):
        raise RuntimeError(f"Incomplete Qwen snapshot: {path}. Expected config.json and every required safetensors weight file.")
    return str(path)


def require_synthesis_ready(cfg: dict) -> None:
    """Check paid-call prerequisites without changing a legacy job's identities."""
    if not resolve_path(cfg, cfg["reference"]["wav"]).is_file():
        raise RuntimeError("Missing reference.wav; no provider call was made")
    qwen_snapshot(cfg)
    verification_model_file(cfg)
    python = executable(cfg, "python_qwen")
    check = subprocess.run([python, "-c", "import torch; print(torch.cuda.is_available())"],
                           text=True, capture_output=True, timeout=60)
    if check.returncode or check.stdout.strip() != "True":
        raise RuntimeError(f"CUDA is unavailable in the configured Qwen environment. No provider call was made. {check.stderr[-1000:]}")


def preflight(cfg: dict, *, providers_needed: bool = False) -> None:
    for key in ("python_qwen", "whisper", "ffmpeg", "ffprobe"):
        cfg["executables"][key] = executable(cfg, key)
    if not resolve_path(cfg, cfg["reference"]["wav"]).is_file():
        raise RuntimeError("Missing reference.wav. Configure a local voice reference; audio is not included in Git.")
    require_schedule_defaults(cfg)
    whisper_model_file(cfg)
    verification_model_file(cfg)
    if (cfg.get("asr_second_pass") or {}).get("enabled"):
        second_pass_model_file(cfg)
    snapshot = Path(qwen_snapshot(cfg))
    # Freeze the local snapshot for new jobs; legacy job cache keys stay valid.
    cfg.setdefault("models", {})["qwen_path"] = str(snapshot)
    cfg["models"]["whisper_path"] = str(whisper_model_file(cfg))
    if "model_revision" not in cfg["qwen3"]:
        if len(snapshot.name) == 40 and all(c in "0123456789abcdef" for c in snapshot.name):
            revision = snapshot.name
        else:
            from .verification import file_identity
            from .util import fingerprint
            revision = fingerprint([file_identity(p) for p in sorted(snapshot.glob("*.safetensors"))] + [file_identity(snapshot / "config.json")])
        cfg["qwen3"]["model_revision"] = revision
    require_synthesis_ready(cfg)
    from .streaming import block_frames
    block_frames(cfg)
    if providers_needed:
        from .providers import require_provider, validate_provider_config
        for role in ("translation", "repair"):
            validate_provider_config(require_provider((cfg.get("providers") or {}).get(role), role))


def named_whisper_model_file(cfg: dict, model: str, model_path: str = "") -> Path:
    effective = dict(cfg)
    effective["whisper"] = dict(cfg["whisper"], model=model or cfg["whisper"]["model"])
    effective["models"] = {k: v for k, v in (cfg.get("models") or {}).items() if k != "whisper_path"}
    if model_path:
        effective["models"]["whisper_path"] = model_path
    elif not model or model == cfg["whisper"]["model"]:
        return whisper_model_file(cfg)
    return whisper_model_file(effective)


def second_pass_model_file(cfg: dict) -> Path:
    block = cfg.get("asr_second_pass") or {}
    return named_whisper_model_file(cfg, block.get("model") or "", block.get("model_path") or "")


def load_preset(name: str) -> dict:
    path = PROJECT_ROOT / "config" / "presets" / f"{name}.json"
    if not path.is_file():
        available = sorted(p.stem for p in (PROJECT_ROOT / "config/presets").glob("*.json"))
        raise RuntimeError(f"Unknown preset {name!r}. Available: {available}")
    return read_json(path)


def apply_preset(cfg: dict, preset: dict) -> dict:
    """Overlay preset groups onto the selected config. Nested objects merge one level deep."""
    out = dict(cfg)
    for key, value in preset.items():
        if key.startswith("_"):
            continue
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            merged = dict(out[key])
            if key == "providers":
                # Preset aliases supply missing roles; an explicit locally
                # configured role keeps its model/reasoning/auth selection.
                merged.update({role: spec for role, spec in value.items()
                               if role not in merged or merged[role].get("kind") in {None, "unconfigured", "none"}})
            else:
                merged.update(value)
            out[key] = merged
        else:
            out[key] = value
    out["preset"] = preset.get("_name") or "custom"
    return out


def verification_model_file(cfg: dict) -> Path:
    quality = cfg.get("quality") or {}
    effective = dict(cfg)
    effective["whisper"] = dict(cfg["whisper"])
    effective["models"] = dict(cfg.get("models") or {})
    if quality.get("asr_model"):
        effective["whisper"]["model"] = quality["asr_model"]
        if quality["asr_model"] != cfg["whisper"]["model"]:
            effective["models"].pop("whisper_path", None)
    if quality.get("asr_model_path"):
        effective["models"]["whisper_path"] = quality["asr_model_path"]
    return whisper_model_file(effective)
