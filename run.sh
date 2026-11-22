#!/usr/bin/env bash
# Filing-Evidence Sectors: run the model jobs (PROTOCOL.md §8, §12, §15), with clean start / stop / resume.
#
#   bash run.sh pipeline   # §13 pipeline check: Qwen3.5-9B, C1, 200 random questions (not a result)
#   bash run.sh start      # start or resume the job queue in the background (returns at once)
#   bash run.sh stop       # finish in-flight questions, stop the model server, free the GPU
#   bash run.sh status     # progress per job, current job, GPU temperature
#
# Jobs run in priority order: C1 for every model, then C2, then C3 (models with a reasoning mode) on the
# 1,000-question subset. Every answer is written to disk as soon as it arrives, and a resumed job skips
# answered questions, so stopping (or a power cut) loses at most the questions in flight. The watchdog guards
# the GPU (temperature, power, hardware slowdown, driver faults) and only stops the work: it never powers off.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$HERE"
LOGS="$ROOT/logs"
LOCK="$ROOT/results/.gpu.lock"
STOP="$ROOT/results/.stop"
PIDF="$ROOT/results/.sectors-run.pid"
# vLLM: this repo's .venv if it has vllm, else VLLM_VENV (environment or .env, e.g. VLLM_VENV=/path/to/venv)
[ -f "$ROOT/.env" ] && VLLM_VENV="${VLLM_VENV:-$(grep -E '^VLLM_VENV=' "$ROOT/.env" | tail -1 | cut -d= -f2-)}"
[ -x "$ROOT/.venv/bin/vllm" ] && VLLM_VENV="$ROOT/.venv"
VLLM_VENV="${VLLM_VENV:?set VLLM_VENV (the virtualenv with vllm) in the environment or .env}"
MODELS=(qwen3.5-9b gpt-oss-20b granite-4.2-8b glm-4.6v-flash ministral-3-8b gemma-3-12b llama-3.1-8b phi-4
        nemotron-nano-9b-v2 olmo-3-7b qwen3-8b)
mkdir -p "$LOGS" "$ROOT/results"
cd "$ROOT"

log() { echo "$(date -Is) $*" | tee -a "$LOGS/sectors-run.log"; }
running() { [ -f "$PIDF" ] && kill -0 "$(cat "$PIDF")" 2>/dev/null; }

has_c3() {  # the model has a reasoning mode (models.yaml request.C3 is not null)
  .venv/bin/python - "$1" <<'EOF'
import sys, yaml
m = yaml.safe_load(open("models.yaml"))["models"][sys.argv[1]]
sys.exit(0 if (m.get("request") or {}).get("C3") is not None else 1)
EOF
}

serve_start() {  # $1 profile; waits until the server answers
  PATH="$VLLM_VENV/bin:$PATH" SERVE_RECORD_DIR="$ROOT/results/serve" \
    "$VLLM_VENV/bin/python" serve.py "$1" > "$LOGS/sectors-serve-$1.log" 2>&1 &
  SERVE_PID=$!
  for _ in $(seq 1 360); do
    grep -q "Application startup complete" "$LOGS/sectors-serve-$1.log" && return 0
    kill -0 "$SERVE_PID" 2>/dev/null || return 1
    [ -e "$STOP" ] && return 1
    sleep 5
  done
  return 1
}

serve_stop() {
  pkill -f "[v]llm serve" ; sleep 10 ; pkill -9 -f "[v]llm serve" ; sleep 3
}

job() {  # $1 profile $2 setup [extra runner args]; returns runner's exit code (3 = stopped on request)
  local p="$1" s="$2"; shift 2
  log "job $p $s $* start"
  .venv/bin/python runner.py "$p" "$s" --set sectors "$@" >> "$LOGS/sectors-run-$p-$s.log" 2>&1
  local rc=$?
  log "job $p $s exit $rc $(grep -E '^accuracy' "$LOGS/sectors-run-$p-$s.log" | tail -1 | cut -c1-120)"
  return $rc
}

done_job() {  # the job finished earlier (summary.json is written only when every question is answered)
  [ -f "$ROOT/results/$1/$2/summary.json" ]
}

queue() {
  exec 9>"$LOCK"; flock 9
  log "queue start (pid $$)"
  bash "$ROOT/watchdog.sh" & disown   # SHUTDOWN=0 is exported by `start`
  for phase in C1 C2 C3; do
    for p in "${MODELS[@]}"; do
      [ -e "$STOP" ] && break 2
      done_job "$p" "$phase" && continue
      if [ "$phase" = C3 ] && ! has_c3 "$p"; then continue; fi
      if ! serve_start "$p"; then
        log "serve $p failed or stopped"; serve_stop
        [ -e "$STOP" ] && break 2
        continue
      fi
      if [ "$phase" = C3 ]; then job "$p" C3 --subset; else job "$p" "$phase"; fi
      rc=$?
      serve_stop
      [ "$rc" = 3 ] && break 2
    done
  done
  serve_stop
  flock -u 9
  if [ -e "$STOP" ]; then log "queue stopped on request; safe to shut down"; else log "queue finished"; fi
  rm -f "$PIDF"
}

case "${1:-status}" in
  start)
    if running; then echo "already running (pid $(cat "$PIDF"))"; exit 0; fi
    rm -f "$STOP"
    SHUTDOWN=0 nohup bash "$0" _queue >> "$LOGS/sectors-run.log" 2>&1 &
    echo $! > "$PIDF"
    echo "started (pid $!). Log: logs/sectors-run.log"
    ;;
  _queue) export SHUTDOWN=0; queue ;;
  stop)
    if ! running; then serve_stop; rm -f "$STOP"; echo "nothing running; GPU free; safe to shut down"; exit 0; fi
    touch "$STOP"
    echo "stopping: finishing the questions in flight…"
    for _ in $(seq 1 60); do running || break; sleep 5; done
    if running; then
      echo "still busy after 5 minutes (long thinking answers); stopping now: in-flight answers are redone later"
      pkill -f "[r]unner.py --set sectors" ; pkill -f "[r]unner.py .* --set sectors"; sleep 5
      kill "$(cat "$PIDF")" 2>/dev/null; rm -f "$PIDF"
    fi
    serve_stop
    pkill -f "[w]atchdog.sh" 2>/dev/null
    rm -f "$STOP"
    echo "stopped. GPU free: $(nvidia-smi --query-gpu=memory.used --format=csv,noheader). Safe to shut down."
    ;;
  pipeline)
    if running; then echo "the queue is running; stop it first"; exit 1; fi
    exec 9>"$LOCK"; flock -n 9 || { echo "GPU busy"; exit 1; }
    serve_start qwen3.5-9b || { echo "serve failed"; serve_stop; exit 1; }
    .venv/bin/python runner.py qwen3.5-9b C1 --set sectors --sample 200 --out-name C1-pipeline \
      2>&1 | tail -3
    serve_stop
    ;;
  status)
    if running; then echo "RUNNING (pid $(cat "$PIDF"))"; else echo "NOT RUNNING"; fi
    grep -E "job .* start|queue" "$LOGS/sectors-run.log" 2>/dev/null | tail -1 | sed 's/^/last: /'
    .venv/bin/python - <<'EOF'
import json, pathlib, yaml
root = pathlib.Path("results")
models = list(yaml.safe_load(open("models.yaml"))["models"])
order = ["qwen3.5-9b","gpt-oss-20b","granite-4.2-8b","glm-4.6v-flash","ministral-3-8b","gemma-3-12b",
         "llama-3.1-8b","phi-4","nemotron-nano-9b-v2","olmo-3-7b","qwen3-8b"]
cfg = yaml.safe_load(open("models.yaml"))["models"]
tot = {"C1": 10000, "C2": 10000, "C3": 1000}
done_all = total_all = 0
for s in ("C1", "C2", "C3"):
    cells = []
    for m in order:
        if s == "C3" and (cfg[m].get("request") or {}).get("C3") is None:
            continue
        f = root / m / s / "answers.jsonl"
        n = sum(1 for _ in f.open()) if f.exists() else 0
        done_all += n; total_all += tot[s]
        cells.append(f"{m} {n * 100 // tot[s]}%")
    print(f"{s}: " + " · ".join(cells))
print(f"overall: {done_all:,} / {total_all:,} answers ({done_all * 100 / total_all:.1f}%)")
EOF
    nvidia-smi --query-gpu=temperature.gpu,power.draw,memory.used --format=csv,noheader | sed 's/^/GPU: /'
    ;;
  *) echo "usage: $0 start|stop|status|pipeline"; exit 1 ;;
esac
