#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
#  run.sh — Start both backend (FastAPI) and frontend (Next.js)
#           locally in a single terminal.
#
#  Usage:
#    chmod +x run.sh   # first time only
#    ./run.sh           # run both servers
#    ./run.sh --backend # run backend only
#    ./run.sh --frontend # run frontend only
# ──────────────────────────────────────────────────────────────

set -e

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"

# Colors for pretty output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# ── Cleanup on exit ──────────────────────────────────────────
cleanup() {
  echo ""
  echo -e "${YELLOW}⏹  Shutting down servers...${NC}"
  [ -n "$BACKEND_PID" ] && kill "$BACKEND_PID" 2>/dev/null && echo -e "${RED}   Backend stopped${NC}"
  [ -n "$FRONTEND_PID" ] && kill "$FRONTEND_PID" 2>/dev/null && echo -e "${RED}   Frontend stopped${NC}"
  wait 2>/dev/null
  echo -e "${GREEN}✔  All servers stopped.${NC}"
  exit 0
}
trap cleanup SIGINT SIGTERM EXIT

# ── Parse flags ──────────────────────────────────────────────
RUN_BACKEND=false
RUN_FRONTEND=false

if [ $# -eq 0 ]; then
  RUN_BACKEND=true
  RUN_FRONTEND=true
else
  for arg in "$@"; do
    case "$arg" in
      --backend)  RUN_BACKEND=true ;;
      --frontend) RUN_FRONTEND=true ;;
      *)
        echo -e "${RED}Unknown flag: $arg${NC}"
        echo "Usage: ./run.sh [--backend] [--frontend]"
        exit 1
        ;;
    esac
  done
fi

# ── Start Backend ────────────────────────────────────────────
if [ "$RUN_BACKEND" = true ]; then
  echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo -e "${GREEN}🚀 Starting Backend (FastAPI + Uvicorn)${NC}"
  echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

  # Activate venv or warn
  if [ -d "$BACKEND_DIR/.venv" ]; then
    source "$BACKEND_DIR/.venv/bin/activate"
    echo -e "${GREEN}   ✔ Virtual environment activated${NC}"
  else
    echo -e "${YELLOW}   ⚠ No .venv found — using system Python${NC}"
  fi

  # Install deps if needed
  if ! python -c "import fastapi, paddle, paddleocr" 2>/dev/null; then
    echo -e "${YELLOW}   ⏳ Installing backend dependencies...${NC}"
    pip install -r "$BACKEND_DIR/requirements.txt" -q
  fi

  # Launch backend
  (cd "$BACKEND_DIR" && uvicorn main:app --reload --host 0.0.0.0 --port 8000) &
  BACKEND_PID=$!
  echo -e "${GREEN}   ✔ Backend running on http://localhost:8000  (PID: $BACKEND_PID)${NC}"
fi

# ── Start Frontend ───────────────────────────────────────────
if [ "$RUN_FRONTEND" = true ]; then
  echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo -e "${GREEN}🚀 Starting Frontend (Vite)${NC}"
  echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

  # Install node_modules if missing
  if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
    echo -e "${YELLOW}   ⏳ Installing frontend dependencies...${NC}"
    (cd "$FRONTEND_DIR" && npm install)
  fi

  # Launch frontend
  (cd "$FRONTEND_DIR" && npm run dev) &
  FRONTEND_PID=$!
  echo -e "${GREEN}   ✔ Frontend running on http://localhost:3000  (PID: $FRONTEND_PID)${NC}"
fi

# ── Wait for processes ───────────────────────────────────────
echo ""
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}✅ All servers are running. Press Ctrl+C to stop.${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
wait
