#!/usr/bin/env bash
set -euo pipefail

export PORT="${PORT:-7860}"
export APP_DATA_DIR="${APP_DATA_DIR:-/data}"
export SQLITE_DB_PATH="${SQLITE_DB_PATH:-$APP_DATA_DIR/app_data.sqlite3}"
export CHROMA_DIR="${CHROMA_DIR:-$APP_DATA_DIR/chroma_db}"
export OLLAMA_MODELS="${OLLAMA_MODELS:-$APP_DATA_DIR/ollama}"
export HF_HOME="${HF_HOME:-$APP_DATA_DIR/huggingface}"
export SENTENCE_TRANSFORMERS_HOME="${SENTENCE_TRANSFORMERS_HOME:-$APP_DATA_DIR/sentence-transformers}"
export OLLAMA_HOST="${OLLAMA_HOST:-127.0.0.1:11434}"
export OLLAMA_URL="${OLLAMA_URL:-http://127.0.0.1:11434/api/generate}"
export OLLAMA_MODEL="${OLLAMA_MODEL:-qwen2.5:0.5b}"
export OLLAMA_TIMEOUT_SECONDS="${OLLAMA_TIMEOUT_SECONDS:-180}"

mkdir -p "$APP_DATA_DIR" "$CHROMA_DIR" "$OLLAMA_MODELS" "$HF_HOME" "$SENTENCE_TRANSFORMERS_HOME"

ollama serve &
OLLAMA_PID=$!

cleanup() {
  kill "$OLLAMA_PID" 2>/dev/null || true
}
trap cleanup EXIT

OLLAMA_BASE_URL="${OLLAMA_URL%/api/generate}"

until curl -fsS "$OLLAMA_BASE_URL/api/tags" >/dev/null; do
  sleep 1
done

if ! ollama list | awk '{print $1}' | grep -qx "$OLLAMA_MODEL"; then
  ollama pull "$OLLAMA_MODEL"
fi

cd /app/backend
exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
