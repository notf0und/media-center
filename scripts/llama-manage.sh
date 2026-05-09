#!/bin/bash

# llama.cpp Service Manager
# Quick commands to manage your LLM service

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

show_help() {
    echo -e "${GREEN}llama.cpp Service Manager${NC}"
    echo ""
    echo "Usage: $0 [command]"
    echo ""
    echo "Commands:"
    echo "  start       - Start the llama.cpp service"
    echo "  stop        - Stop the llama.cpp service"
    echo "  restart     - Restart the llama.cpp service"
    echo "  logs        - View service logs (follow mode)"
    echo "  status      - Show service status and resource usage"
    echo "  test        - Test the API with a simple query"
    echo "  benchmark   - Run a speed benchmark"
    echo "  models      - List available models"
    echo "  health      - Check service health"
    echo "  rebuild     - Rebuild the Docker image"
    echo ""
}

check_running() {
    if ! docker ps | grep -q llama-cpp; then
        echo -e "${RED}✗ llama-cpp service is not running${NC}"
        echo "Start it with: $0 start"
        exit 1
    fi
}

case "$1" in
    start)
        echo -e "${GREEN}Starting llama-cpp service...${NC}"
        docker-compose up -d llama-cpp
        echo -e "${GREEN}✓ Service started${NC}"
        echo "Check logs: $0 logs"
        ;;
    
    stop)
        echo -e "${YELLOW}Stopping llama-cpp service...${NC}"
        docker-compose stop llama-cpp
        echo -e "${GREEN}✓ Service stopped${NC}"
        ;;
    
    restart)
        echo -e "${YELLOW}Restarting llama-cpp service...${NC}"
        docker-compose restart llama-cpp
        echo -e "${GREEN}✓ Service restarted${NC}"
        ;;
    
    logs)
        echo -e "${GREEN}Following llama-cpp logs (Ctrl+C to exit)...${NC}"
        docker logs -f llama-cpp
        ;;
    
    status)
        echo -e "${GREEN}=== Service Status ===${NC}"
        if docker ps | grep -q llama-cpp; then
            echo -e "${GREEN}✓ Running${NC}"
            echo ""
            echo -e "${GREEN}=== Resource Usage ===${NC}"
            docker stats llama-cpp --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}"
            echo ""
            echo -e "${GREEN}=== Recent Logs ===${NC}"
            docker logs --tail 10 llama-cpp
        else
            echo -e "${RED}✗ Not running${NC}"
        fi
        ;;
    
    test)
        check_running
        echo -e "${GREEN}Testing llama.cpp API...${NC}"
        echo ""
        curl -s http://localhost:8080/v1/chat/completions \
          -H "Content-Type: application/json" \
          -d '{
            "messages": [
              {"role": "user", "content": "Say hello in one sentence."}
            ],
            "max_tokens": 50
          }' | python3 -m json.tool || echo -e "${RED}Failed to connect${NC}"
        ;;
    
    benchmark)
        check_running
        echo -e "${GREEN}Running speed benchmark...${NC}"
        echo "Query: Count from 1 to 20"
        echo ""
        time curl -s http://localhost:8080/v1/chat/completions \
          -H "Content-Type: application/json" \
          -d '{
            "messages": [
              {"role": "user", "content": "Count from 1 to 20"}
            ],
            "max_tokens": 100
          }' > /dev/null
        echo ""
        echo -e "${GREEN}Check tokens/sec in logs:${NC}"
        docker logs llama-cpp 2>&1 | grep -i "tokens per second" | tail -5
        ;;
    
    models)
        echo -e "${GREEN}=== Installed Models ===${NC}"
        ls -lh config/llama-cpp/models/ 2>/dev/null || echo "No models directory found"
        echo ""
        echo -e "${YELLOW}To change model:${NC}"
        echo "  cd config/llama-cpp/models"
        echo "  rm model.gguf"
        echo "  wget <model-url> -O model.gguf"
        echo "  $0 restart"
        ;;
    
    health)
        check_running
        echo -e "${GREEN}Checking health endpoint...${NC}"
        RESPONSE=$(curl -s http://localhost:8080/health || echo "Failed")
        if [ "$RESPONSE" != "Failed" ]; then
            echo -e "${GREEN}✓ Service is healthy${NC}"
            echo "$RESPONSE"
        else
            echo -e "${RED}✗ Health check failed${NC}"
        fi
        ;;
    
    rebuild)
        echo -e "${YELLOW}Rebuilding llama-cpp Docker image...${NC}"
        docker-compose build --no-cache llama-cpp
        echo ""
        echo -e "${GREEN}✓ Image rebuilt${NC}"
        echo "Restart service: $0 restart"
        ;;
    
    *)
        show_help
        exit 1
        ;;
esac
