#!/usr/bin/env bash
# Guarded lifecycle control for the local Gradle-run Fineract development server.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ACTION="${1:-}"
FINERACT_HOST="${FINERACT_HOST:-127.0.0.1}"
FINERACT_PORT="${FINERACT_PORT:-8443}"
STOP_TIMEOUT_SECONDS="${FINERACT_PROCESS_STOP_TIMEOUT_SECONDS:-60}"
PID_FILE="${FINERACT_PROCESS_PID_FILE:-$ROOT/.fineract-devrun.pid}"
LOG_FILE="${FINERACT_PROCESS_LOG_FILE:-$ROOT/logs/fineract-devrun.log}"

usage() {
  cat <<'EOF'
Usage: ./scripts/local-fineract.sh start|stop|restart|status

Controls only a local Fineract ServerApplication running from this checkout.
It refuses to stop an unknown process that happens to occupy the Fineract port.
EOF
}

die() {
  echo "ERROR: $*" >&2
  exit 1
}

[[ "$ACTION" =~ ^(start|stop|restart|status)$ ]] || {
  usage >&2
  exit 2
}
[[ "$STOP_TIMEOUT_SECONDS" =~ ^[0-9]+$ ]] || die "Stop timeout must be an integer"
command -v lsof >/dev/null 2>&1 || die "Required command not found: lsof"

listener_pids() {
  lsof -nP -tiTCP:"$FINERACT_PORT" -sTCP:LISTEN 2>/dev/null || true
}

describe_status() {
  local pids
  pids="$(listener_pids)"
  if [[ -z "$pids" ]]; then
    echo "Fineract is stopped on ${FINERACT_HOST}:${FINERACT_PORT}"
    return 1
  fi
  echo "Fineract is listening on ${FINERACT_HOST}:${FINERACT_PORT} (PID ${pids//$'\n'/,})"
}

require_owned_fineract_process() {
  local pid="$1" command_line
  command_line="$(ps -p "$pid" -o command= 2>/dev/null || true)"
  [[ "$command_line" == *"org.apache.fineract.ServerApplication"* ]] || \
    die "Refusing to stop PID $pid: the listener is not Fineract ServerApplication"
  [[ "$command_line" == *"$ROOT"* ]] || \
    die "Refusing to stop PID $pid: Fineract is not running from $ROOT"
}

stop_fineract() {
  local pids pid deadline
  pids="$(listener_pids)"
  if [[ -z "$pids" ]]; then
    rm -f "$PID_FILE"
    echo "Fineract is already stopped"
    return
  fi
  while IFS= read -r pid; do
    [[ -n "$pid" ]] || continue
    require_owned_fineract_process "$pid"
  done <<<"$pids"
  while IFS= read -r pid; do
    [[ -n "$pid" ]] || continue
    kill -TERM "$pid"
  done <<<"$pids"

  deadline=$((SECONDS + STOP_TIMEOUT_SECONDS))
  while [[ -n "$(listener_pids)" && $SECONDS -lt $deadline ]]; do
    sleep 1
  done
  [[ -z "$(listener_pids)" ]] || die "Fineract did not stop within ${STOP_TIMEOUT_SECONDS}s"
  rm -f "$PID_FILE"
  echo "Stopped local Fineract"
}

start_fineract() {
  local launcher_pid
  if describe_status >/dev/null 2>&1; then
    echo "Fineract is already running"
    return
  fi
  if [[ -f "$PID_FILE" ]]; then
    launcher_pid="$(<"$PID_FILE")"
    if [[ "$launcher_pid" =~ ^[0-9]+$ ]] && kill -0 "$launcher_pid" 2>/dev/null; then
      echo "Fineract launch is already in progress (PID $launcher_pid)"
      return
    fi
    rm -f "$PID_FILE"
  fi

  mkdir -p "$(dirname "$LOG_FILE")"
  (
    cd "$ROOT"
    nohup ./gradlew devRun >>"$LOG_FILE" 2>&1 </dev/null &
    echo "$!" >"$PID_FILE"
  )
  launcher_pid="$(<"$PID_FILE")"
  sleep 1
  kill -0 "$launcher_pid" 2>/dev/null || \
    die "Fineract launcher exited immediately; inspect $LOG_FILE"
  echo "Started local Fineract launcher (PID $launcher_pid); log: $LOG_FILE"
}

case "$ACTION" in
  start)
    start_fineract
    ;;
  stop)
    stop_fineract
    ;;
  restart)
    stop_fineract
    start_fineract
    ;;
  status)
    describe_status
    ;;
esac
