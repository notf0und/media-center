#!/bin/bash
# All runtime settings are read from environment variables on every container start.
# To change any setting: update docker-compose.yml and run:
#   docker-compose up -d --force-recreate voicebm
#
# Available Sherpa-ONNX speaker recognition models (set SHERPA_MODEL_NAME):
#
#   English models (recommended for English-speaking households):
#     nemo_en_titanet_small.onnx          (~38 MB)  - Default, VoiceBM recommended
#     nemo_en_titanet_large.onnx          (~97 MB)  - Higher accuracy, more RAM
#     nemo_en_speakerverification_speakernet.onnx (~22 MB) - Smallest NeMo
#     wespeaker_en_voxceleb_CAM++.onnx    (~28 MB)  - WeSpeaker CAM++
#     wespeaker_en_voxceleb_CAM++_LM.onnx (~28 MB)  - WeSpeaker CAM++ with LM
#     wespeaker_en_voxceleb_resnet152_LM.onnx (~75 MB)
#     wespeaker_en_voxceleb_resnet221_LM.onnx (~91 MB)
#     wespeaker_en_voxceleb_resnet293_LM.onnx (~109 MB) - Largest/most accurate
#     3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx (~28 MB)
#     3dspeaker_speech_eres2net_sv_en_voxceleb_16k.onnx (~25 MB)
#
#   Bilingual Chinese+English:
#     3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx (~27 MB)
#
# All models are downloaded from:
#   https://github.com/k2-fsa/sherpa-onnx/releases/tag/speaker-recongition-models
set -e

DATA_DIR="${VOICEBM_BASE:-/data}"
MODELS_DIR="${DATA_DIR}/models"
SHERPA_MODEL_NAME="${SHERPA_MODEL_NAME:-nemo_en_titanet_small.onnx}"
SHERPA_MODEL="${SHERPA_MODEL:-${MODELS_DIR}/${SHERPA_MODEL_NAME}}"
MQTT_BROKER="${MQTT_BROKER:-localhost}"
MQTT_PORT="${MQTT_PORT:-1883}"
MQTT_USER="${MQTT_USER:-}"
MQTT_PASS="${MQTT_PASS:-}"

# ---------------------------------------------------------------------------
# Ensure runtime directories exist
# ---------------------------------------------------------------------------
mkdir -p \
    "${DATA_DIR}/enroll" \
    "${DATA_DIR}/recordings" \
    "${DATA_DIR}/embeddings" \
    "${DATA_DIR}/pending_active/recordings" \
    "${DATA_DIR}/meta" \
    "${MODELS_DIR}" \
    "${DATA_DIR}/stt_requests"

# ---------------------------------------------------------------------------
# Download chosen Sherpa-ONNX speaker recognition model (first run only)
# ---------------------------------------------------------------------------
if [ ! -f "${SHERPA_MODEL}" ]; then
    echo "[voicebm] Downloading model: ${SHERPA_MODEL_NAME}"
    MODEL_URL="https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/${SHERPA_MODEL_NAME}"
    curl -fsSL -o "${SHERPA_MODEL}" "${MODEL_URL}"
    echo "[voicebm] Model ready at ${SHERPA_MODEL}"
fi

# ---------------------------------------------------------------------------
# Fill placeholders in service templates → /app/*.py (runs on every start,
# so changing env vars + docker-compose up -d --force-recreate applies them)
# ---------------------------------------------------------------------------
fill_template() {
    local src="$1"
    local dst="$2"
    sed \
        -e "s|{VOICEBM_BASE}|${DATA_DIR}|g" \
        -e "s|{SHERPA_BIN}|/app/sherpa_embed.py|g" \
        -e "s|{SHERPA_MODEL}|${SHERPA_MODEL}|g" \
        -e "s|{MQTT_BROKER}|${MQTT_BROKER}|g" \
        -e "s|{MQTT_PORT}|${MQTT_PORT}|g" \
        -e "s|{MQTT_USER}|${MQTT_USER}|g" \
        -e "s|{MQTT_PASS}|${MQTT_PASS}|g" \
        -e "s|{CONDA_PATH}|/usr|g" \
        "${src}" > "${dst}"
}

GLOBAL_TMPL="/app/templates/global"
fill_template "${GLOBAL_TMPL}/voicebm_config.py.template"          /app/voicebm_config.py
fill_template "${GLOBAL_TMPL}/voicebm_stt_service.py.template"     /app/voicebm_stt_service.py
fill_template "${GLOBAL_TMPL}/voicebm_global_publisher.py.template" /app/voicebm_global_publisher.py
fill_template "${GLOBAL_TMPL}/audio_server.py.template"            /app/audio_server.py

[ -f "${GLOBAL_TMPL}/enrollment_watcher.py.template" ] && \
    fill_template "${GLOBAL_TMPL}/enrollment_watcher.py.template" /app/enrollment_watcher.py

[ -f "${GLOBAL_TMPL}/voicebm_dashboard.py.template" ] && \
    fill_template "${GLOBAL_TMPL}/voicebm_dashboard.py.template" /app/voicebm_dashboard.py

# ---------------------------------------------------------------------------
# Start services in background (all configuration is env-driven)
# ---------------------------------------------------------------------------
echo "[voicebm] Starting voicebm_stt_service..."
python3 /app/voicebm_stt_service.py &

echo "[voicebm] Starting voicebm_global_publisher..."
python3 /app/voicebm_global_publisher.py &

if [ -f /app/audio_server.py ]; then
    echo "[voicebm] Starting audio_server on port 9090..."
    python3 /app/audio_server.py &
fi

if [ -f /app/enrollment_watcher.py ]; then
    echo "[voicebm] Starting enrollment_watcher..."
    python3 /app/enrollment_watcher.py &
fi

if [ -f /app/voicebm_dashboard.py ]; then
    echo "[voicebm] Starting voicebm_dashboard on port ${VOICEBM_DASHBOARD_PORT:-5055}..."
    python3 /app/voicebm_dashboard.py &
fi

echo "[voicebm] Starting Wyoming proxy on port ${VOICEBM_WYOMING_PORT:-10301}..."
python3 /app/voicebm_wyoming_proxy.py &

echo "[voicebm] All services started. Model: ${SHERPA_MODEL_NAME}"
wait
