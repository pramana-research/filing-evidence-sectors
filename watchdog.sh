#!/usr/bin/env bash
# GPU guard rail for long benchmark runs. Every 60 s it reads the 4090's temperature, power and hardware-slowdown
# flags. If something looks wrong it stops the run cleanly: run_all.sh / loadcheck.sh first (so no next model
# starts), then runner.py and the vLLM server. Runs resume from answers.jsonl, so nothing answered is lost.
# Exits on its own once no benchmark script is running.
#
# Trips when:
#   - GPU temperature >= TEMP_MAX (default 85 C) on 2 checks in a row
#   - power draw >= POWER_MAX (default 480 W) on 2 checks in a row
#   - the driver reports a hardware slowdown (HW slowdown / HW thermal / power brake)
#   - nvidia-smi fails (GPU not responding)
#   - the driver logs a GPU fault (an "NVRM: Xid" line in the kernel log since the watchdog started)
#
# After a trip it waits SHUTDOWN_DELAY seconds (default 120) and powers the machine off. To cancel during the
# wait: touch results/.no-shutdown. To never power off: SHUTDOWN=0.
#
#   bash watchdog.sh        # log: logs/watchdog.log
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
LOG="$HERE/logs/watchdog.log"
TEMP_MAX="${TEMP_MAX:-85}"
POWER_MAX="${POWER_MAX:-480}"
SHUTDOWN="${SHUTDOWN:-1}"
SHUTDOWN_DELAY="${SHUTDOWN_DELAY:-120}"
CANCEL="$HERE/results/.no-shutdown"
HW_SLOWDOWN=$((0x08 | 0x40 | 0x80))   # clocks_event_reasons: HW slowdown, HW thermal slowdown, HW power brake

log() { echo "$(date -Is) $*" >> "$LOG"; }

stop_run() {
  log "TRIP: $1 -- stopping the benchmark"
  pkill -f "[r]un_all.sh" ; pkill -f "[l]oadcheck.sh" ; pkill -f "[s]ets/sectors/run.sh"
  pkill -f "[r]unner.py" ; pkill -f "[v]llm serve"
  sleep 15
  pkill -9 -f "[v]llm serve"
  log "stopped. Resume later with the same run_all.sh command."
  command -v notify-send >/dev/null && notify-send -u critical "filing-evidence watchdog" \
    "Benchmark stopped: $1. Powering off in ${SHUTDOWN_DELAY}s unless $CANCEL exists."
  if [ "$SHUTDOWN" = 1 ]; then
    log "powering off in ${SHUTDOWN_DELAY}s (cancel: touch $CANCEL)"
    sleep "$SHUTDOWN_DELAY"
    if [ -e "$CANCEL" ]; then log "power-off cancelled by $CANCEL"; rm -f "$CANCEL"; exit 1; fi
    log "powering off"
    sync
    systemctl poweroff
  fi
  exit 1
}

START="$(date '+%Y-%m-%d %H:%M:%S')"
log "start (temp max ${TEMP_MAX} C, power max ${POWER_MAX} W, power off after trip: ${SHUTDOWN}, delay ${SHUTDOWN_DELAY}s)"
hot=0; heavy=0; i=0
while pgrep -f "^bash .*(run_all|loadcheck|sets/sectors/run)\.sh" >/dev/null; do
  if ! r=$(nvidia-smi --query-gpu=temperature.gpu,power.draw,clocks_event_reasons.active \
                      --format=csv,noheader,nounits 2>/dev/null); then
    stop_run "nvidia-smi failed (GPU not responding)"
  fi
  IFS=', ' read -r temp power reasons <<< "$r"
  power=${power%.*}
  if (( temp >= TEMP_MAX )); then hot=$((hot + 1)); else hot=0; fi
  if (( power >= POWER_MAX )); then heavy=$((heavy + 1)); else heavy=0; fi
  (( hot >= 2 )) && stop_run "temperature ${temp} C"
  (( heavy >= 2 )) && stop_run "power ${power} W"
  (( reasons & HW_SLOWDOWN )) && stop_run "hardware slowdown flag ${reasons}"
  xid=$(journalctl -k --since "$START" --no-pager 2>/dev/null | grep -m1 "NVRM: Xid")
  [ -n "$xid" ] && stop_run "driver fault: ${xid##*NVRM: }"
  # one line every 10 minutes so the log shows the card's history
  (( i++ % 10 == 0 )) && log "ok ${temp} C ${power} W ${reasons}"
  sleep 60
done
log "no benchmark running; exiting"
