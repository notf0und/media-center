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
VOICEBM_HOST="${VOICEBM_HOST:-localhost}"

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
    "${DATA_DIR}/stt_requests" \
    "${DATA_DIR}/bin"

# Create the Sherpa embedding wrapper expected by voicebm_stt_service
cat > "${DATA_DIR}/bin/embed_stt.sh" << EOF
#!/usr/bin/env bash
set -euo pipefail
INPUT="\$1"
OUTPUT="\$2"
exec python3 /app/sherpa_embed.py --model "${SHERPA_MODEL}" --wav "\$INPUT" --out "\$OUTPUT"
EOF
chmod +x "${DATA_DIR}/bin/embed_stt.sh"

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
        -e "s|10\.50\.60\.58|${VOICEBM_HOST}|g" \
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

# Patch dashboard: voicebm_stt_service writes pending.json as a plain array but
# the dashboard's get_pending() expects {"entries": [...]}. Normalize on read.
python3 - << 'PYEOF'
import re, sys
path = '/app/voicebm_dashboard.py'
src = open(path).read()
old = "    return load_json(PENDING_FILE, {'entries': []})"
new = (
    "    data = load_json(PENDING_FILE, {'entries': []})\n"
    "    if isinstance(data, list):\n"
    "        return {'entries': data}\n"
    "    return data"
)
if old in src:
    open(path, 'w').write(src.replace(old, new, 1))
    print('[voicebm] Patched dashboard get_pending() for array format')
else:
    print('[voicebm] WARNING: dashboard patch target not found — skipping', file=sys.stderr)
PYEOF

# Patch dashboard: enroll_pending() and reject_pending() are stubs — replace them
# with real implementations that delegate to voicebm_stt_service via MQTT.
python3 - << 'PYEOF'
import sys
path = '/app/voicebm_dashboard.py'
src = open(path).read()

old_enroll = '''\
@app.route('/api/pending/enroll', methods=['POST'])
def enroll_pending():
    """Enroll a pending voice"""
    data = request.get_json()
    pending_id = data.get('pending_id')
    display_name = data.get('display_name', '').strip()
    
    if not pending_id or not display_name:
        return jsonify({'error': 'Missing required fields'}), 400
    
    person_id = display_name.lower().replace(' ', '_')
    
    # TODO: Implement enrollment logic
    # This would move files from pending_active/ to enroll/{person_id}/
    
    return jsonify({'success': True, 'person_id': person_id})'''

new_enroll = '''\
@app.route('/api/pending/enroll', methods=['POST'])
def enroll_pending():
    """Enroll a pending voice by delegating to voicebm_stt_service via MQTT."""
    data = request.get_json()
    pending_id = data.get('pending_id')
    display_name = data.get('display_name', '').strip()

    if not pending_id or not display_name:
        return jsonify({'error': 'Missing required fields'}), 400

    person_id = display_name.lower().replace(' ', '_')

    payload = json.dumps({
        'id': pending_id,
        'person_id': person_id,
        'display_name': display_name,
    })
    try:
        publish_to_mqtt('voicebm/pending_active/enroll', payload, qos=1, retain=False)
        return jsonify({'success': True, 'person_id': person_id})
    except Exception as e:
        return jsonify({'error': str(e)}), 500'''

old_reject = '''\
@app.route('/api/pending/reject', methods=['POST'])
def reject_pending():
    """Reject a pending voice"""
    data = request.get_json()
    pending_id = data.get('pending_id')
    
    if not pending_id:
        return jsonify({'error': 'Missing pending_id'}), 400
    
    # TODO: Implement rejection logic
    # This would delete files from pending_active/
    
    return jsonify({'success': True})'''

new_reject = '''\
@app.route('/api/pending/reject', methods=['POST'])
def reject_pending():
    """Reject a pending voice by delegating to voicebm_stt_service via MQTT."""
    data = request.get_json()
    pending_id = data.get('pending_id')

    if not pending_id:
        return jsonify({'error': 'Missing pending_id'}), 400

    try:
        publish_to_mqtt('voicebm/pending_active/reject', json.dumps({'id': pending_id}), qos=1, retain=False)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500'''

patched = src
count = 0
for old, new in [(old_enroll, new_enroll), (old_reject, new_reject)]:
    if old in patched:
        patched = patched.replace(old, new, 1)
        count += 1

open(path, 'w').write(patched)
print(f'[voicebm] Patched {count}/2 enrollment stubs in dashboard')
if count < 2:
    print('[voicebm] WARNING: some enrollment patches not applied', file=sys.stderr)
PYEOF

# Patch dashboard: fix add_active_to_gallery (list vs dict + missing fields)
python3 /app/dashboard_patches.py

# Fix any stale hardcoded IPs in existing pending.json (from previous runs)
PENDING_JSON="${DATA_DIR}/pending_active/pending.json"
if [ -f "${PENDING_JSON}" ]; then
    sed -i "s|10\.50\.60\.58|${VOICEBM_HOST}|g" "${PENDING_JSON}"
    echo "[voicebm] Fixed audio URLs in pending.json"
fi

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
