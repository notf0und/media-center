#!/bin/bash

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}   llama.cpp Setup for Voice Assistant${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# Create model directory
MODEL_DIR="./config/llama-cpp/models"
mkdir -p "$MODEL_DIR"

echo -e "${YELLOW}Available models:${NC}"
echo "1. Phi-3.5-mini Q4_K_M (2.3GB) - RECOMMENDED - Best quality/speed balance"
echo "2. Llama 3.2 3B Q4_K_M (2.0GB) - Good alternative"
echo "3. Llama 3.2 1B Q4_K_M (800MB) - Fastest, less capable"
echo "4. Qwen2.5 0.5B Q4_K_M (400MB) - Ultra lightweight"
echo ""
read -p "Select model (1-4) [1]: " model_choice
model_choice=${model_choice:-1}

case $model_choice in
    1)
        MODEL_NAME="Phi-3.5-mini-instruct"
        MODEL_URL="https://huggingface.co/bartowski/Phi-3.5-mini-instruct-GGUF/resolve/main/Phi-3.5-mini-instruct-Q4_K_M.gguf"
        MODEL_SIZE="2.3GB"
        ;;
    2)
        MODEL_NAME="Llama-3.2-3B-Instruct"
        MODEL_URL="https://huggingface.co/bartowski/Llama-3.2-3B-Instruct-GGUF/resolve/main/Llama-3.2-3B-Instruct-Q4_K_M.gguf"
        MODEL_SIZE="2.0GB"
        ;;
    3)
        MODEL_NAME="Llama-3.2-1B-Instruct"
        MODEL_URL="https://huggingface.co/bartowski/Llama-3.2-1B-Instruct-GGUF/resolve/main/Llama-3.2-1B-Instruct-Q4_K_M.gguf"
        MODEL_SIZE="800MB"
        ;;
    4)
        MODEL_NAME="Qwen2.5-0.5B-Instruct"
        MODEL_URL="https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q4_k_m.gguf"
        MODEL_SIZE="400MB"
        ;;
    *)
        echo -e "${RED}Invalid choice. Using Phi-3.5-mini (default)${NC}"
        MODEL_NAME="Phi-3.5-mini-instruct"
        MODEL_URL="https://huggingface.co/bartowski/Phi-3.5-mini-instruct-GGUF/resolve/main/Phi-3.5-mini-instruct-Q4_K_M.gguf"
        MODEL_SIZE="2.3GB"
        ;;
esac

echo ""
echo -e "${GREEN}Downloading ${MODEL_NAME} (${MODEL_SIZE})...${NC}"
echo "This may take a while depending on your internet connection."
echo ""

# Download model
wget --progress=bar:force:noscroll -O "$MODEL_DIR/model.gguf" "$MODEL_URL" || {
    echo -e "${RED}Failed to download model${NC}"
    exit 1
}

echo ""
echo -e "${GREEN}Model downloaded successfully!${NC}"
echo ""

# Build Docker image
echo -e "${YELLOW}Building llama.cpp Docker image...${NC}"
docker-compose build llama-cpp || {
    echo -e "${RED}Failed to build Docker image${NC}"
    exit 1
}

echo ""
echo -e "${GREEN}Starting llama-cpp service...${NC}"
docker-compose up -d llama-cpp

echo ""
echo -e "${GREEN}Waiting for service to be ready (60 seconds)...${NC}"
sleep 60

# Test the service
echo ""
echo -e "${YELLOW}Testing llama.cpp service...${NC}"
RESPONSE=$(curl -s http://localhost:8080/health 2>/dev/null || echo "")

if [ -n "$RESPONSE" ]; then
    echo -e "${GREEN}✓ Service is running!${NC}"
    echo ""
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}   Setup Complete!${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo ""
    echo "Service URL: http://llama.test (via Traefik)"
    echo "Direct URL: http://localhost:8080"
    echo ""
    echo "Test with:"
    echo '  curl http://localhost:8080/v1/chat/completions \'
    echo '    -H "Content-Type: application/json" \'
    echo '    -d '\''{'
    echo '      "messages": [{"role": "user", "content": "Hello!"}],'
    echo '      "temperature": 0.7,'
    echo '      "max_tokens": 100'
    echo '    }'\'''
    echo ""
    echo "Home Assistant integration URL: http://llama-cpp:8080"
    echo ""
else
    echo -e "${RED}✗ Service failed to start. Check logs:${NC}"
    echo "  docker logs llama-cpp"
    exit 1
fi
