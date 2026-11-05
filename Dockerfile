FROM python:3.11-slim

# build-essential, cmake — для llama-cpp-python, если нет готового колеса.
# libgomp1 — для torch. curl — для healthcheck.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    libgomp1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# CPU-torch первым: без CUDA-колёс (~10 GB → ~200 MB).
# sentence-transformers затем увидит готовый torch и не будет переустанавливать.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ src/
COPY config/ config/
COPY data/prompts/ data/prompts/
COPY start.sh .
RUN chmod +x start.sh && sed -i 's/\r$//' start.sh

ENV PYTHONPATH=/app/src
ENV LLM_MODEL_PATH=/app/data/models/QVikhr-3-1.7B-Instruction-noreasoning-Q4_K_M.gguf
ENV EMBED_PATH=/app/data/models/multilingual-e5-small

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=300s --retries=5 \
    CMD curl -f http://localhost:8000/ready || exit 1

CMD ["./start.sh"]
