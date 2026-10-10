#!/usr/bin/env bash
# Explicitly launch one new run/resume; never stop or replace another unit.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if (($# < 2 || $# > 6)); then
  echo 'Usage: scripts/start-host-verification.sh VIDEO NAME [CONFIG [MIC GAME MIXED]]' >&2
  exit 1
fi
VIDEO="$(realpath "$1")"
NAME="$2"
CONFIG="$(realpath "${3:-$ROOT/config/local.json}")"
if [[ ! "$NAME" =~ ^[A-Za-z0-9._-]+$ ]]; then echo 'Invalid job name' >&2; exit 1; fi
if [[ ! -f "$VIDEO" || ! -f "$CONFIG" ]]; then echo 'Source/config file unavailable' >&2; exit 1; fi
systemctl --user show-environment >/dev/null
UNIT="aidub-verify-$NAME-$(date -u +%Y%m%dT%H%M%SZ)"
ENV_ARGS=("--setenv=AIDUB_CONFIG=$CONFIG")
while read -r var; do
  if [[ "$var" =~ ^[A-Za-z_][A-Za-z0-9_]*$ && -n "${!var:-}" ]]; then
    ENV_ARGS+=("--setenv=$var=${!var}")
  fi
done < <(python3 - "$CONFIG" <<'PY'
import json,sys
cfg=json.load(open(sys.argv[1]))
for spec in cfg.get('providers',{}).values():
    for key in ['api_key_env','base_url_env','model_env']:
        if spec.get(key):print(spec[key])
PY
)
systemd-run --user --unit="$UNIT" --working-directory="$ROOT" --property=KillMode=control-group \
  "${ENV_ARGS[@]}" /usr/bin/bash "$ROOT/scripts/host-verification-job.sh" "$CONFIG" "$VIDEO" "$NAME" \
  "${4:-2}" "${5:-1}" "${6:-0}"
printf 'Unit: %s\nJob: %s\nLogs: %s\n' "$UNIT" "$NAME" "$ROOT/runs/hardening/host/$NAME"
