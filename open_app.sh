#!/bin/bash
# Open Cycling Coach in the browser, starting it first if it isn't running.
# Used by the Cycling Coach app in ~/Applications; also fine to run by hand.
cd "$(dirname "$0")"
PORT=8599
URL="http://localhost:$PORT"
if ! lsof -iTCP:$PORT -sTCP:LISTEN >/dev/null 2>&1; then
    nohup ./venv/bin/streamlit run app.py --server.port $PORT --server.headless true \
        > data/app.log 2>&1 &
    for _ in $(seq 1 60); do
        curl -s -o /dev/null "$URL" && break
        sleep 0.5
    done
fi
open "$URL"
