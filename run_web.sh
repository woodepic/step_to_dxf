#!/usr/bin/env bash
# Launch the plynest web UI on http://127.0.0.1:8000
set -euo pipefail
cd "$(dirname "$0")"

PY=./venv/bin/python
[ -x "$PY" ] || PY=python3

exec "$PY" -c "
import sys, pathlib, webbrowser, threading
sys.path.insert(0, str(pathlib.Path('src').resolve()))
import uvicorn
from plynest.web.app import app
threading.Timer(1.2, lambda: webbrowser.open('http://127.0.0.1:8000')).start()
uvicorn.run(app, host='127.0.0.1', port=8000)
"
