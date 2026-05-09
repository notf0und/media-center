# Stage 1: build ikawrakow/ik_llama.cpp
# This fork has a merged AVX2-optimized Q1_0_G128 kernel (PR #1570) which gives
# ~30-50 tok/s on a 6-core AVX2 i5-8500 vs ~0.2 tok/s from the old Mintplex scalar path.
FROM ubuntu:22.04 AS builder

RUN apt-get update && apt-get install -yq \
    build-essential git cmake libcurl4-openssl-dev curl libgomp1 wget \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
RUN git clone --depth 1 https://github.com/ikawrakow/ik_llama.cpp.git llama.cpp

WORKDIR /build/llama.cpp
RUN cmake -B build \
    -DGGML_NATIVE=ON \
    -DLLAMA_CURL=ON \
    && cmake --build build --config Release -j$(nproc) --target llama-server

# Collect all shared libraries produced by the build
RUN mkdir -p /build/libs && find build -name "*.so" -exec cp {} /build/libs \;

# Stage 2: lean runtime image
FROM ubuntu:22.04

RUN apt-get update && apt-get install -yq \
    libgomp1 curl wget ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /build/llama.cpp/build/bin/llama-server /usr/local/bin/llama-server
COPY --from=builder /build/libs/ /usr/local/lib/
RUN ldconfig

RUN mkdir -p /data

VOLUME /data
EXPOSE 8085

CMD ["/bin/bash", "/data/run.sh"]
