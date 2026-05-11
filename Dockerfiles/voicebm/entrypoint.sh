#!/bin/bash
# VoiceBM Entrypoint
# ==================
# All runtime settings are read from environment variables and stored in /data/config.json
# Configuration is applied on every container start, so changes are applied immediately:
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

DATA_DIR="/data"  # hardcoded, always /data (mounted from host via volumes)
MODELS_DIR="${DATA_DIR}/models"
STT_MODELS_DIR="${DATA_DIR}/stt-models"

# Export for config_generator.py
export DATA_DIR

# Set defaults for environment variables
SHERPA_MODEL_NAME="${SHERPA_MODEL_NAME:-nemo_en_titanet_small.onnx}"
SHERPA_MODEL="${SHERPA_MODEL:-${MODELS_DIR}/${SHERPA_MODEL_NAME}}"
MQTT_BROKER="${MQTT_BROKER:-localhost}"
MQTT_PORT="${MQTT_PORT:-1883}"
MQTT_USER="${MQTT_USER:-}"
MQTT_PASS="${MQTT_PASS:-}"
VOICEBM_ENABLED="${VOICEBM_ENABLED:-true}"

# Embedded STT configuration
VOICEBM_STT_MODEL="${VOICEBM_STT_MODEL:-cohere-transcribe}"
VOICEBM_STT_LANGUAGE="${VOICEBM_STT_LANGUAGE:-en}"
VOICEBM_STT_THREADS="${VOICEBM_STT_THREADS:-4}"

# ---------------------------------------------------------------------------
# Ensure runtime directories exist with proper permissions
# ---------------------------------------------------------------------------
mkdir -p \
    "${DATA_DIR}/enroll" \
    "${DATA_DIR}/recordings" \
    "${DATA_DIR}/embeddings" \
    "${DATA_DIR}/pending_active/recordings" \
    "${DATA_DIR}/meta" \
    "${MODELS_DIR}" \
    "${STT_MODELS_DIR}" \
    "${DATA_DIR}/stt_requests" \
    "${DATA_DIR}/bin"

# Set directories to 755 so they're readable/traversable
chmod -R 755 "${DATA_DIR}" 2>/dev/null || true

echo "[voicebm] Services will run as root (container user)"

# ---------------------------------------------------------------------------
# Generate or update config.json from environment variables
# ---------------------------------------------------------------------------
echo "[voicebm] Configuring VoiceBM from environment variables..."
python3 /app/config_generator.py

# ---------------------------------------------------------------------------
# Download chosen Sherpa-ONNX speaker recognition model (first run only)
# ---------------------------------------------------------------------------
if [ ! -f "${SHERPA_MODEL}" ]; then
    echo "[voicebm] Downloading speaker recognition model: ${SHERPA_MODEL_NAME}"
    MODEL_URL="https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/${SHERPA_MODEL_NAME}"
    curl -fsSL -o "${SHERPA_MODEL}" "${MODEL_URL}"
    echo "[voicebm] Speaker model ready at ${SHERPA_MODEL}"
fi

# ---------------------------------------------------------------------------
# Download chosen Sherpa-ONNX STT model (first run only)
# ---------------------------------------------------------------------------
echo "[voicebm] Downloading STT model: ${VOICEBM_STT_MODEL}"
python3 - << PYEOF
import sys
sys.path.insert(0, "/app")
import voicebm_stt_engine
try:
    voicebm_stt_engine.download_stt_model("${VOICEBM_STT_MODEL}", "${STT_MODELS_DIR}")
    print("[voicebm] STT model ready")
except Exception as e:
    print(f"[voicebm] ERROR downloading STT model: {e}", file=sys.stderr)
    sys.exit(1)
PYEOF

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
# Runtime patches for service files:
# 1. Fix dashboard's get_pending() to handle array format from voicebm_stt_service
# 2. Fix voicebm_stt_service.py to read audio_url from config.json instead of hardcoding
# 3. Fix voicebm_dashboard.py to read port from config.json instead of hardcoding
# ---------------------------------------------------------------------------
python3 << PYTHON_FIX_SERVICES
import re
import json

config_file = '${DATA_DIR}/config.json'
stt_file = '/app/voicebm_stt_service.py'
dashboard_file = '/app/voicebm_dashboard.py'

# Load config to get audio_server.base_url and dashboard.port
try:
    with open(config_file, 'r') as f:
        config = json.load(f)
    audio_base_url = config.get('audio_server', {}).get('base_url', 'http://10.50.60.58:9090')
    dashboard_port = config.get('dashboard', {}).get('port', 5000)
    print(f"[voicebm] Loaded config: audio_base_url={audio_base_url}, dashboard_port={dashboard_port}")
except Exception as e:
    print(f"[voicebm] WARNING: Could not load config.json: {e}")
    audio_base_url = 'http://10.50.60.58:9090'
    dashboard_port = 5000

# Fix 1: dashboard's get_pending() to handle both array and dict formats
try:
    with open(dashboard_file, 'r') as f:
        content = f.read()
    
    old_pattern = r'def get_pending\(\) -> dict:\s+"""Load pending\.json"""\s+return load_json\(PENDING_FILE, \{\'entries\': \[\]\}\)'
    new_function = '''def get_pending() -> dict:
    """Load pending.json - handle both array and dict formats"""
    data = load_json(PENDING_FILE, {'entries': []})
    # If it's an array (from voicebm_stt_service), wrap it in entries dict
    if isinstance(data, list):
        return {'entries': data}
    return data'''
    
    if re.search(old_pattern, content):
        content = re.sub(old_pattern, new_function, content)
        with open(dashboard_file, 'w') as f:
            f.write(content)
        print("[voicebm] ✓ Fixed get_pending() to handle array format")
    else:
        print("[voicebm] • get_pending() already fixed or not found")
except Exception as e:
    print(f"[voicebm] ERROR fixing get_pending(): {e}")

# Fix 2: voicebm_stt_service.py to use audio_base_url from config
try:
    with open(stt_file, 'r') as f:
        content = f.read()
    
    # Replace hardcoded audio_url with dynamic one from config
    # Find the line with audio_url and replace it with one that reads from config
    lines = content.split('\n')
    new_lines = []
    modified = False
    for i, line in enumerate(lines):
        # Match the line with trailing comma
        if '"audio_url": f"http://10.50.60.58:9090/pending/{pending_id}.wav",' in line:
            indent = len(line) - len(line.lstrip())
            new_line = ' ' * indent + f'"audio_url": f"{audio_base_url}/pending/{{pending_id}}.wav",'
            new_lines.append(new_line)
            modified = True
            print("[voicebm] ✓ Fixed audio_url to use HOST_AUDIO from config")
        else:
            new_lines.append(line)
    
    if modified:
        with open(stt_file, 'w') as f:
            f.write('\n'.join(new_lines))
    else:
        print("[voicebm] • audio_url already uses dynamic URL or not found")
except Exception as e:
    print(f"[voicebm] ERROR fixing audio_url: {e}")

# Fix 3: voicebm_dashboard.py to use port from config
try:
    with open(dashboard_file, 'r') as f:
        content = f.read()
    
    # Replace app.run(host='0.0.0.0', port=5000, ...)
    old_run_pattern = r"app\.run\(host='0\.0\.0\.0', port=5000"
    new_run_pattern = f"app.run(host='0.0.0.0', port={dashboard_port}"
    
    if re.search(old_run_pattern, content):
        content = re.sub(old_run_pattern, new_run_pattern, content)
        with open(dashboard_file, 'w') as f:
            f.write(content)
        print(f"[voicebm] ✓ Fixed dashboard port to {dashboard_port} from config")
    else:
        print("[voicebm] • dashboard port already updated or not found")
except Exception as e:
    print(f"[voicebm] ERROR fixing dashboard port: {e}")

print("[voicebm] Service patching complete")
PYTHON_FIX_SERVICES

# ---------------------------------------------------------------------------
# Apply dashboard patches from separate file
# ---------------------------------------------------------------------------
if [ -f /app/dashboard_patches.py ]; then
    echo "[voicebm] Applying dashboard patches..."
    python3 /app/dashboard_patches.py
else
    echo "[voicebm] dashboard_patches.py not found, skipping dashboard patches"
fi

# ---------------------------------------------------------------------------
# Start services using background processes (with logs visible via docker-compose logs)
# ---------------------------------------------------------------------------
echo "[voicebm] Starting services..."

# Check if VOICEBM is enabled (can be disabled to STT-only mode)
if [ "${VOICEBM_ENABLED}" = "true" ] || [ "${VOICEBM_ENABLED}" = "1" ]; then
    echo "[voicebm] Starting voicebm_stt_service..."
    python3 -u /app/voicebm_stt_service.py &

    echo "[voicebm] Starting voicebm_global_publisher..."
    python3 -u /app/voicebm_global_publisher.py &

    if [ -f /app/audio_server.py ]; then
        echo "[voicebm] Starting audio_server on port 9090..."
        python3 -u /app/audio_server.py &
    fi

    if [ -f /app/enrollment_watcher.py ]; then
        echo "[voicebm] Starting enrollment_watcher..."
        python3 -u /app/enrollment_watcher.py &
    fi

    if [ -f /app/voicebm_dashboard.py ]; then
        echo "[voicebm] Starting voicebm_dashboard on port 5000..."
        python3 -u /app/voicebm_dashboard.py &
    fi
    
    echo "[voicebm] VoiceBM services started"
else
    echo "[voicebm] VoiceBM disabled (VOICEBM_ENABLED=false). STT-only mode."
fi

echo "[voicebm] Starting Wyoming proxy on port ${VOICEBM_WYOMING_PORT:-10301}..."
env VOICEBM_STT_MODEL="${VOICEBM_STT_MODEL}" \
    VOICEBM_STT_LANGUAGE="${VOICEBM_STT_LANGUAGE}" \
    VOICEBM_STT_THREADS="${VOICEBM_STT_THREADS}" \
    VOICEBM_STT_MODEL_DIR="${STT_MODELS_DIR}" \
    python3 -u /app/voicebm_wyoming_proxy.py
