#!/bin/bash

BASE_DIR="/home/yvofxbku/apathy-screen-app"
PID_FILE="$BASE_DIR/uvicorn.pid"

cd "$BASE_DIR" || exit 1

if [ ! -f "$PID_FILE" ]; then
  echo "PIDファイルがありません。uvicorn は起動していない可能性があります。"
  exit 0
fi

PID=$(cat "$PID_FILE")

if ps -p "$PID" > /dev/null 2>&1; then
  echo "uvicorn (PID: $PID) を停止します..."
  kill "$PID"
  # 念のため少し待ってから確認
  sleep 2
  if ps -p "$PID" > /dev/null 2>&1; then
    echo "まだ生きているので強制終了します..."
    kill -9 "$PID"
  fi
  echo "停止しました。"
else
  echo "PID $PID のプロセスはすでに存在しませんでした。"
fi

rm -f "$PID_FILE"

