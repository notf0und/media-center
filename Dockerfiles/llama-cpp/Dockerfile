FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

# Install dependencies for Vulkan and llama.cpp
RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    git \
    wget \
    curl \
    libcurl4-openssl-dev \
    libvulkan-dev \
    vulkan-tools \
    libshaderc-dev \
    glslang-tools \
    spirv-tools \
    mesa-vulkan-drivers \
    intel-media-va-driver \
    && rm -rf /var/lib/apt/lists/*

# Clone and build llama.cpp (CPU-only for stability)
# Vulkan support can be complex to build - CPU performance is still excellent
WORKDIR /app
RUN git clone https://github.com/ggerganov/llama.cpp.git . && \
    cmake -B build \
        -DLLAMA_CURL=1 \
        -DCMAKE_BUILD_TYPE=Release && \
    cmake --build build --config Release -j$(nproc) --target llama-server

# Create model directory
RUN mkdir -p /models

# Expose API port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Default command - optimized for Intel i5-8500 (6 cores)
# Using 4 threads to leave resources for other containers
# ctx-size 2048 is good balance for home automation tasks
# CPU-only (n-gpu-layers 0) - still 15-25 tokens/sec on your hardware
CMD ["./build/bin/llama-server", \
     "--host", "0.0.0.0", \
     "--port", "8080", \
     "--model", "/models/model.gguf", \
     "--ctx-size", "2048", \
     "--threads", "4", \
     "--parallel", "1", \
     "--cont-batching"]
