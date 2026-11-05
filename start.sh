#!/bin/sh
set -e
cd /app
export LLM_MODEL_PATH="${LLM_MODEL_PATH:-/app/data/models/QVikhr-3-1.7B-Instruction-noreasoning-Q4_K_M.gguf}"
exec python -m uvicorn api:app --host 0.0.0.0 --port 8000
