#!/usr/bin/env bash
# Emergency stop for the Filing-Evidence Sectors runs, made to be typed from a phone over SSH (e.g. Tailscale).
#
#   bash ~/filing-evidence/sets/sectors/emergency.sh            # stop the run cleanly, then power off
#   bash ~/filing-evidence/sets/sectors/emergency.sh --now      # stop at once (in-flight answers redone later), power off
#   bash ~/filing-evidence/sets/sectors/emergency.sh --stay-on  # stop the run cleanly, keep the PC on
#   bash ~/filing-evidence/sets/sectors/emergency.sh --dry-run  # only say what would happen
#
# Nothing answered is lost either way: every answer is on disk, and `run.sh start` resumes. Powering off asks
# for your password if the system requires it.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
MODE="${1:-}"
say() { echo "[$(date '+%H:%M:%S')] $*"; }

if [ "$MODE" = "--dry-run" ]; then
  say "would stop the run ($(bash "$HERE/run.sh" status 2>/dev/null | head -1)), free the GPU, then power off"
  exit 0
fi

if [ "$MODE" = "--now" ]; then
  say "stopping at once"
  touch "$ROOT/results/.stop"
  pkill -f "[s]ets/sectors/run.sh _queue"
  pkill -f "[r]unner.py .*--set sectors"
  pkill -f "[v]llm serve"; sleep 8; pkill -9 -f "[v]llm serve"
  pkill -f "[w]atchdog.sh"
  rm -f "$ROOT/results/.sectors-run.pid" "$ROOT/results/.stop"
else
  say "stopping cleanly (finishing the questions in flight, at most 5 minutes)"
  bash "$HERE/run.sh" stop
fi

say "GPU memory in use: $(nvidia-smi --query-gpu=memory.used --format=csv,noheader 2>/dev/null || echo '?')"
if [ "$MODE" = "--stay-on" ]; then
  say "run stopped; the PC stays on"
  exit 0
fi
say "powering off now"
sync
systemctl poweroff || sudo poweroff
