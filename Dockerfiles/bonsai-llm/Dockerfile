# Stage 1: build prism-ml-llama.cpp
FROM debian:bookworm AS builder

RUN apt-get update && apt-get install -y \
    git cmake make g++ wget \
    && rm -rf /var/lib/apt/lists/*

# Clone and build the Mintplex-Labs prism fork (branch: prism)
# This fork adds Q1_0_g128 1-bit quantization CPU kernels
WORKDIR /build
RUN git clone --depth 1 -b prism \
    https://github.com/Mintplex-Labs/prism-ml-llama.cpp.git llama.cpp

WORKDIR /build/llama.cpp
RUN cmake -B build \
    -DCMAKE_BUILD_TYPE=Release \
    -DLLAMA_NATIVE=ON \
    -DBUILD_SHARED_LIBS=OFF \
    && cmake --build build -j$(nproc) --target llama-server

# Stage 2: lean runtime image
FROM debian:bookworm-slim

# Runtime dependencies for the compiled binary
RUN apt-get update && apt-get install -y \
    libgomp1 wget ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /build/llama.cpp/build/bin/llama-server /usr/local/bin/llama-server

RUN mkdir -p /data

VOLUME /data
EXPOSE 8085

CMD ["/bin/bash", "/data/run.sh"]
