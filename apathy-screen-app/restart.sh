#!/bin/bash

BASE_DIR="/home/yvofxbku/apathy-screen-app"

cd "$BASE_DIR" || exit 1

echo "uvicorn を再起動します..."

./stop.sh
sleep 1
./start.sh

