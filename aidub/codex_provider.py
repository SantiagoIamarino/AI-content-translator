"""Explicit subscription-only Codex configuration; never reads credential files."""
import os
import shutil
import subprocess
from pathlib import Path

from .util import sha256_file

CONTRACT_VERSION = "aidub.codex_chatgpt.v2"
DECISION_CONTRACT = "aidub.review_decision.v2"
ROOT = Path(__file__).resolve().parents[1]
CONTROLS = {
    "model_provider": '"openai"',
    "forced_login_method": '"chatgpt"',
    "approval_policy": '"never"',
    "web_search": '"disabled"',
    "project_doc_max_bytes": "0",
    "features.shell_tool": "false",
    "features.multi_agent": "false",
    "features.apps": "false",
    "features.plugins": "false",
    "features.hooks": "false",
    "features.memories": "false",
    "features.browser_use": "false",
    "features.computer_use": "false",
    "features.image_generation": "false",
    "tools.view_image": "false",
}


def clean_environment():
    # Retain OS/keyring/TLS access, never inherited API keys, gateways, remote
    # sessions or provider overrides. Authentication stays in the CLI's store.
    names = {"PATH", "HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "TMPDIR",
             "CODEX_HOME", "DBUS_SESSION_BUS_ADDRESS", "XDG_RUNTIME_DIR",
             "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME",
             "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE"}
    return {k: v for k, v in os.environ.items() if k in names}


def settings(spec):
    if spec.get("auth", "chatgpt") != "chatgpt":
        raise ValueError("codex_chatgpt requires auth=chatgpt; API billing/fallback is prohibited")
    model = spec.get("model")
    effort = spec.get("reasoning")
    if not isinstance(model, str) or not model.strip() or effort not in {"low", "medium", "high", "xhigh", "max"}:
        raise ValueError("codex_chatgpt requires explicit model and reasoning")
    executable = shutil.which(spec.get("codex", "codex"))
    if not executable:
        raise ValueError("Codex CLI is unavailable; install/configure it separately, then sign in with ChatGPT")
    return executable, model, effort


def chatgpt_ready(executable):
    result = subprocess.run([executable, "login", "status"], env=clean_environment(),
                            capture_output=True, text=True, timeout=20)
    if result.returncode or (result.stdout + result.stderr).strip() != "Logged in using ChatGPT":
        raise ValueError("ChatGPT authentication is required. Run codex login separately; no API fallback is allowed.")


def provenance(spec):
    executable, model, effort = settings(spec)
    result = subprocess.run([executable, "--version"], env=clean_environment(),
                            capture_output=True, text=True, timeout=20, check=True)
    return {"contract": CONTRACT_VERSION, "model": model, "reasoning": effort, "auth": "chatgpt",
            "cli_version": result.stdout.strip(), "cli_sha256": sha256_file(Path(executable)),
            "adapter_sha256": sha256_file(ROOT / "scripts/provider_codex.py"),
            "configuration_sha256": sha256_file(Path(__file__)),
            "decision_contract": DECISION_CONTRACT,
            "review_code_sha256": sha256_file(ROOT / "aidub/review.py"),
            "sandbox": "read-only", "ignore_user_config": True, "ignore_rules": True,
            "ephemeral": True, "controls": CONTROLS}


def command(spec, request, response, role):
    import sys
    executable, model, effort = settings(spec)
    return [sys.executable, str(ROOT / "scripts/provider_codex.py"), "--codex", executable,
            "--model", model, "--reasoning", effort, "--auth", "chatgpt",
            "--request", str(request), "--response", str(response), "--role", role]
