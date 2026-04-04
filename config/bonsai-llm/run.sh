#!/bin/bash
set -e

MODEL_URL="${BONSAI_MODEL_URL:-https://huggingface.co/prism-ml/Bonsai-1.7B-gguf/resolve/main/Bonsai-1.7B.gguf}"
MODEL_PATH="/data/Bonsai-1.7B.gguf"
PORT="${BONSAI_PORT:-8085}"
THREADS="${BONSAI_THREADS:-4}"
CTX_SIZE="${BONSAI_CTX_SIZE:-8192}"
PARALLEL="${BONSAI_PARALLEL:-2}"

echo "=== bonsai-llm ==="
echo "  Model : $MODEL_PATH"
echo "  Port  : $PORT"
echo "  Threads: $THREADS"

if [ ! -f "$MODEL_PATH" ]; then
    echo "Downloading Bonsai-1.7B model (~240 MB)..."
    wget --progress=dot:giga -O "${MODEL_PATH}.tmp" "$MODEL_URL"
    mv "${MODEL_PATH}.tmp" "$MODEL_PATH"
    echo "Model download complete."
else
    echo "Model already downloaded, skipping."
fi

echo "Starting llama-server on port $PORT..."
exec llama-server \
    -m "$MODEL_PATH" \
    --host 0.0.0.0 \
    --port "$PORT" \
    --threads "$THREADS" \
    -c "$CTX_SIZE" \
    --parallel "$PARALLEL" \
    --cont-batching
