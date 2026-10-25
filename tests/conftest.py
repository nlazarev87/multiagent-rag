import os
from pathlib import Path

os.environ["LLM_MODEL_PATH"] = str(
    Path(__file__).resolve().parents[1] / "data" / "models" / "qwen2.5-1.5b-instruct-q4_k_m.gguf"
)
