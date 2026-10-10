#!/usr/bin/env bash
# Called by the launcher in a persistent, uniquely named user service.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG="$1"
VIDEO="$2"
NAME="$3"
MIC="$4"
GAME="$5"
MIXED="$6"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOGS="$ROOT/runs/hardening/host/$NAME/$STAMP"
mkdir -p "$LOGS"
export PYTHONUNBUFFERED=1
MONITOR=""
finish() {
  if [[ -n "$MONITOR" ]]; then kill "$MONITOR" 2>/dev/null || true; wait "$MONITOR" 2>/dev/null || true; fi
}
trap finish EXIT
if command -v nvidia-smi >/dev/null; then
  nvidia-smi --query-gpu=timestamp,memory.used,utilization.gpu --format=csv -l 2 >"$LOGS/gpu.csv" 2>"$LOGS/gpu-errors.log" &
  MONITOR=$!
fi
set +e
python3 "$ROOT/scripts/run-measured.py" "$LOGS/resources.json" "$ROOT/bin/aidub" --config "$CONFIG" auto "$VIDEO" --name "$NAME" \
  --mic-ordinal "$MIC" --game-ordinal "$GAME" --mixed-ordinal "$MIXED" \
  >"$LOGS/pipeline.log" 2>"$LOGS/resources.log"
CODE=$?
set -e
printf '%s\n' "$CODE" >"$LOGS/exit-code.txt"
exit "$CODE"
