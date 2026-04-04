#!/bin/bash
# Download model if not present, then start Wyoming + API servers

MODEL=${SHERPA_MODEL:-cohere-transcribe}
WYOMING_PORT=${SHERPA_WYOMING_PORT:-10303}
API_PORT=${SHERPA_API_PORT:-5054}
NUM_THREADS=${SHERPA_NUM_THREADS:-4}
LANGUAGE=${SHERPA_LANGUAGE:-en}

echo "=== sherpa-onnx-asr ==="
echo "  Model    : $MODEL"
echo "  Language : $LANGUAGE"
echo "  Wyoming  : $WYOMING_PORT"
echo "  API      : $API_PORT"

# Download model using Python model_registry
python3 /data/model_registry.py --download --model "$MODEL" --dir /data

# Start Wyoming server (background)
python3 /data/wyoming_server.py --port "$WYOMING_PORT" --model "$MODEL" --language "$LANGUAGE" --num-threads "$NUM_THREADS" &
WYOMING_PID=$!

sleep 3

# Start OpenAI API server (background)
SHERPA_MODEL="$MODEL" SHERPA_API_PORT="$API_PORT" SHERPA_NUM_THREADS="$NUM_THREADS" SHERPA_LANGUAGE="$LANGUAGE" \
    python3 /data/openai_api_server.py &
API_PID=$!

shutdown() {
    echo "Shutting down..."
    kill $WYOMING_PID $API_PID 2>/dev/null
    wait $WYOMING_PID $API_PID 2>/dev/null
    exit 0
}

trap shutdown SIGTERM SIGINT

echo "Services running. Waiting..."
wait -n
shutdown
