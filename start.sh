#!/bin/sh
set -e
cd /app
exec python -m uvicorn api:app --host 0.0.0.0 --port 8000
