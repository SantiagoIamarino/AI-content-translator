from pathlib import Path

from .util import read_json

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIRMED_REFERENCE_TEXT = (
    "okay so uh we have this kind of dogs i don't know they're coming from the church "
    "i guess okay they almost hit me okay shouldn't oh he bite me i'm gonna try to use "
    "the shotgun this time try to shotgun him there you go there you go another one"
)


def load_config(path: Path | None = None) -> dict:
    cfg_path = path or (PROJECT_ROOT / "config" / "default.json")
    cfg = read_json(cfg_path)
    cfg["_config_path"] = str(cfg_path.resolve())
    cfg["_project_root"] = str(PROJECT_ROOT)
    return cfg


def resolve_path(cfg: dict, value: str) -> Path:
    path = Path(value)
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
    if reference_text(cfg) != CONFIRMED_REFERENCE_TEXT:
        raise RuntimeError("Reference transcript does not match the user-confirmed text.")
