#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd -P)"
AGENT_ROOT="$REPO_ROOT/narrow-shopping-agent"
FRONTEND_ROOT="$REPO_ROOT/demo-frontend"
TRACE_ROOT="$REPO_ROOT/trace-visualizer"
CATALOG_PATH="$AGENT_ROOT/data/catalog.jsonl"
SKIP_INSTALL=false

usage() {
  cat <<'EOF'
Usage: ./scripts/run_demo.sh [options]

Start the Shopping Copilot Vue frontend, local Python API, and Trace Visualizer.
All services bind to 127.0.0.1 and are stopped together with Ctrl+C.

Options:
  --catalog-path PATH  Use a catalog.jsonl at PATH.
  --skip-install       Reuse the existing Python and Node dependencies.
  -h, --help           Show this help.
EOF
}

while (($#)); do
  case "$1" in
    --catalog-path|--catalog)
      (($# >= 2)) || { echo "Missing value for $1" >&2; exit 2; }
      CATALOG_PATH="$2"
      shift 2
      ;;
    --skip-install)
      SKIP_INSTALL=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

case "$(uname -s)" in
  Darwin|Linux) ;;
  *) echo "This script supports macOS and Linux. Use scripts/run_demo.ps1 on Windows." >&2; exit 2 ;;
esac

command -v node >/dev/null || { echo "Node.js 22.13 or newer is required." >&2; exit 1; }
command -v npm >/dev/null || { echo "npm is required." >&2; exit 1; }
read -r NODE_MAJOR NODE_MINOR < <(node -p 'process.versions.node.split(".").slice(0, 2).join(" ")')
if ((NODE_MAJOR < 22 || (NODE_MAJOR == 22 && NODE_MINOR < 13))); then
  echo "Node.js 22.13 or newer is required; found $(node --version)." >&2
  exit 1
fi

if [[ "$CATALOG_PATH" != /* ]]; then
  CATALOG_PATH="$(pwd -P)/$CATALOG_PATH"
fi
if [[ ! -f "$CATALOG_PATH" ]]; then
  echo "Warning: catalog not found at $CATALOG_PATH" >&2
  echo "Pages and saved results remain available; chat and new evaluations require a catalog." >&2
fi

if [[ "$SKIP_INSTALL" == false ]]; then
  command -v uv >/dev/null || { echo "uv is required to install Python dependencies." >&2; exit 1; }
  (
    cd "$AGENT_ROOT"
    uv sync --extra web --extra ltr --extra openai --group dev --cache-dir .uv-cache
  )
  for directory in "$FRONTEND_ROOT" "$TRACE_ROOT"; do
    if [[ ! -d "$directory/node_modules" ]]; then
      (
        cd "$directory"
        npm ci --cache .npm-cache --no-audit --no-fund
      )
    fi
  done
fi

PYTHON_EXE="$AGENT_ROOT/.venv/bin/python"
[[ -x "$PYTHON_EXE" ]] || {
  echo "Missing $PYTHON_EXE; run once without --skip-install." >&2
  exit 1
}
for directory in "$FRONTEND_ROOT" "$TRACE_ROOT"; do
  [[ -d "$directory/node_modules" ]] || {
    echo "Missing $directory/node_modules; run once without --skip-install." >&2
    exit 1
  }
done

if command -v lsof >/dev/null; then
  for port in 5173 8000 3000; do
    if lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null | head -n 1 | grep -q .; then
      echo "Port $port is already in use. Stop the existing Demo services and retry." >&2
      exit 1
    fi
  done
fi

LOG_ROOT="$REPO_ROOT/demo_runs/server-logs"
mkdir -p "$LOG_ROOT"
STAMP="$(date '+%Y%m%d-%H%M%S')"
PIDS=()
NAMES=()
CLEANED_UP=false

start_service() {
  local name="$1"
  local working_directory="$2"
  shift 2
  (
    cd "$working_directory"
    exec "$@"
  ) >"$LOG_ROOT/$STAMP-$name.out.log" 2>"$LOG_ROOT/$STAMP-$name.err.log" &
  PIDS+=("$!")
  NAMES+=("$name")
}

terminate_tree() {
  local pid="$1"
  local child
  while read -r child; do
    [[ -n "$child" ]] && terminate_tree "$child"
  done < <(pgrep -P "$pid" 2>/dev/null || true)
  kill -TERM "$pid" 2>/dev/null || true
}

cleanup() {
  [[ "$CLEANED_UP" == false ]] || return
  CLEANED_UP=true
  if ((${#PIDS[@]})); then
    echo
    echo "Stopping Shopping Copilot services..."
    for pid in "${PIDS[@]}"; do terminate_tree "$pid"; done
    for pid in "${PIDS[@]}"; do wait "$pid" 2>/dev/null || true; done
  fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

PYTHON_PATH_VALUE="$AGENT_ROOT/src:$AGENT_ROOT${PYTHONPATH:+:$PYTHONPATH}"
start_service api "$AGENT_ROOT" env PYTHONPATH="$PYTHON_PATH_VALUE" \
  "$PYTHON_EXE" -m shopping_agent.web --catalog "$CATALOG_PATH"
start_service frontend "$FRONTEND_ROOT" npm run dev -- --host 127.0.0.1 --port 5173
start_service trace "$TRACE_ROOT" npm run dev

all_services_alive() {
  local index
  for index in "${!PIDS[@]}"; do
    if ! kill -0 "${PIDS[$index]}" 2>/dev/null; then
      echo "Service '${NAMES[$index]}' exited; check $LOG_ROOT/$STAMP-${NAMES[$index]}.err.log" >&2
      return 1
    fi
  done
}

wait_for_url() {
  local name="$1"
  local url="$2"
  local attempt
  for attempt in {1..120}; do
    all_services_alive || return 1
    if curl --silent --fail --max-time 2 --output /dev/null "$url"; then
      return 0
    fi
    sleep 0.5
  done
  echo "Timed out waiting for $name at $url; check logs in $LOG_ROOT." >&2
  return 1
}

wait_for_url "API" "http://127.0.0.1:8000/api/health"
wait_for_url "Vue frontend" "http://127.0.0.1:5173/"
wait_for_url "Trace Visualizer" "http://127.0.0.1:3000/"

echo "Shopping Copilot: http://127.0.0.1:5173"
echo "API:              http://127.0.0.1:8000"
echo "Trace:            http://127.0.0.1:3000"
echo "Local-only mode. Press Ctrl+C to stop all three services."
echo "Logs: $LOG_ROOT"

while true; do
  all_services_alive
  sleep 1
done
