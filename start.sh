#!/bin/bash
BASE_DIR="/home/yvofxbku/apathy-screen-app"
PID_FILE="$BASE_DIR/uvicorn.pid"
LOG_FILE="$BASE_DIR/uvicorn.log"
UVICORN_CMD="/home/yvofxbku/miniconda3/envs/apathy/bin/uvicorn"
APP_MODULE="app.main:app"
HOST="0.0.0.0"
PORT="8000"

cd "$BASE_DIR" || exit 1

if [ -f "$PID_FILE" ]; then
  PID=$(cat "$PID_FILE")
  if ps -p "$PID" > /dev/null 2>&1; then
    echo "uvicorn はすでに起動中です (PID: $PID)"
    exit 0
  else
    echo "古い PID ファイルを削除します (PID: $PID)"
    rm -f "$PID_FILE"
  fi
fi

echo "uvicorn を起動します..."
nohup "$UVICORN_CMD" "$APP_MODULE" --host "$HOST" --port "$PORT" > "$LOG_FILE" 2>&1 &

NEW_PID=$!
echo "$NEW_PID" > "$PID_FILE"

echo "起動しました (PID: $NEW_PID)"
echo "ログ: $LOG_FILE"
