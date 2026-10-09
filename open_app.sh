#!/bin/bash
# Open Cycling Coach in the browser, starting it first if it isn't running.
# Used by the Cycling Coach app in ~/Applications; also fine to run by hand.
# A running copy started from older code is restarted, since it keeps the old code in memory.
cd "$(dirname "$0")"
PORT=8599
URL="http://localhost:$PORT"
STAMP=data/app.version
VERSION=$(git rev-parse HEAD 2>/dev/null)$(git status --porcelain 2>/dev/null | md5 -q)

running() { lsof -tiTCP:$PORT -sTCP:LISTEN 2>/dev/null; }

if [ -n "$(running)" ] && [ "$(cat $STAMP 2>/dev/null)" != "$VERSION" ]; then
    kill $(running) 2>/dev/null
    for _ in $(seq 1 20); do [ -z "$(running)" ] && break; sleep 0.25; done
fi
if [ -z "$(running)" ]; then
    nohup ./venv/bin/streamlit run app.py --server.port $PORT --server.headless true \
        > data/app.log 2>&1 &
    echo "$VERSION" > $STAMP
    for _ in $(seq 1 60); do
        curl -s -o /dev/null "$URL/_stcore/health" && break
        sleep 0.5
    done
fi
open "$URL"
