#!/bin/bash

BASE_DIR="/home/yvofxbku/apathy-screen-app"
PID_FILE="$BASE_DIR/uvicorn.pid"

cd "$BASE_DIR" || exit 1

if [ ! -f "$PID_FILE" ]; then
  echo "uvicorn は起動していません (PIDファイルなし)。"
  exit 0
fi

PID=$(cat "$PID_FILE")

if ps -p "$PID" > /dev/null 2>&1; then
  echo "uvicorn は起動中です (PID: $PID)。"
else
  echo "PIDファイルはありますが、プロセスは存在しません (PID: $PID)。"
fi

