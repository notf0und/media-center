"""
Post-fill patches for voicebm_dashboard.py.
Fixes bugs in VoiceBM's dashboard that are incompatible with our Docker setup.
Run by entrypoint.sh after fill_template() completes.
"""
import sys
import re
import json
from pathlib import Path

DASHBOARD = "/app/voicebm_dashboard.py"
CONFIG_FILE = "/data/config.json"


def patch(src, old, new, label):
    if old in src:
        print(f"[voicebm] Patched: {label}")
        return src.replace(old, new, 1)
    print(f"[voicebm] WARNING: patch target not found: {label}", file=sys.stderr)
    return src


# Read dashboard
if not Path(DASHBOARD).exists():
    print(f"[voicebm] Dashboard not found at {DASHBOARD}, skipping patches")
    sys.exit(0)

src = open(DASHBOARD).read()

# Load config to get dashboard.port
try:
    with open(CONFIG_FILE, 'r') as f:
        config = json.load(f)
    dashboard_port = config.get('dashboard', {}).get('port', 5000)
    print(f"[voicebm] Loaded config: dashboard_port={dashboard_port}")
except Exception as e:
    print(f"[voicebm] WARNING: Could not load config.json: {e}")
    dashboard_port = 5000

# ---------------------------------------------------------------------------
# 0. Fix get_pending() to handle both array and dict formats
# ---------------------------------------------------------------------------

try:
    old_pattern = r'def get_pending\(\) -> dict:\s+"""Load pending\.json"""\s+return load_json\(PENDING_FILE, \{\'entries\': \[\]\}\)'
    new_function = '''def get_pending() -> dict:
    """Load pending.json - handle both array and dict formats"""
    data = load_json(PENDING_FILE, {'entries': []})
    # If it's an array (from voicebm_stt_service), wrap it in entries dict
    if isinstance(data, list):
        return {'entries': data}
    return data'''
    
    if re.search(old_pattern, src):
        src = re.sub(old_pattern, new_function, src)
        print("[voicebm] ✓ Fixed get_pending() to handle array format")
    else:
        print("[voicebm] • get_pending() already fixed or not found")
except Exception as e:
    print(f"[voicebm] ERROR fixing get_pending(): {e}")

# ---------------------------------------------------------------------------
# 0.5 Fix enroll_pending() - delegate to voicebm_stt_service via MQTT
#    Original: just returns success without doing anything (TODO stub)
#    Fixed: publishes to voicebm/pending_active/enroll for backend processing
# ---------------------------------------------------------------------------

m_enroll = re.search(
    r"(@app\.route\('/api/pending/enroll'.*?)\n(@app\.route)",
    src,
    re.DOTALL,
)
if m_enroll:
    old_enroll = m_enroll.group(1)
    new_enroll = """\
@app.route('/api/pending/enroll', methods=['POST'])
def enroll_pending():
    \"\"\"Enroll a pending voice by delegating to voicebm_stt_service via MQTT.\"\"\"
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
        return jsonify({'error': str(e)}), 500

"""
    src = src.replace(old_enroll, new_enroll, 1)
    print("[voicebm] ✓ Patched: enroll_pending()")
else:
    print("[voicebm] WARNING: enroll_pending not found", file=sys.stderr)

# ---------------------------------------------------------------------------
# 0.6 Fix reject_pending() - delegate to voicebm_stt_service via MQTT
#    Original: just returns success without doing anything (TODO stub)
#    Fixed: publishes to voicebm/pending_active/reject for backend processing
# ---------------------------------------------------------------------------

m_reject = re.search(
    r"(@app\.route\('/api/pending/reject'.*?)\n(if __name__|@app\.route)",
    src,
    re.DOTALL,
)
if m_reject:
    old_reject = m_reject.group(1)
    new_reject = """\
@app.route('/api/pending/reject', methods=['POST'])
def reject_pending():
    \"\"\"Reject a pending voice by delegating to voicebm_stt_service via MQTT.\"\"\"
    data = request.get_json()
    pending_id = data.get('pending_id')

    if not pending_id:
        return jsonify({'error': 'Missing pending_id'}), 400

    try:
        publish_to_mqtt('voicebm/pending_active/reject', json.dumps({'id': pending_id}), qos=1, retain=False)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

"""
    src = src.replace(old_reject, new_reject, 1)
    print("[voicebm] ✓ Patched: reject_pending()")
else:
    print("[voicebm] WARNING: reject_pending not found", file=sys.stderr)

# ---------------------------------------------------------------------------
# 1. Fix dashboard port to use config.json instead of hardcoding
# ---------------------------------------------------------------------------

try:
    old_run_pattern = r"app\.run\(host='0\.0\.0\.0', port=5000"
    new_run_pattern = f"app.run(host='0.0.0.0', port={dashboard_port}"
    
    if re.search(old_run_pattern, src):
        src = re.sub(old_run_pattern, new_run_pattern, src)
        print(f"[voicebm] ✓ Fixed dashboard port to {dashboard_port} from config")
    else:
        print("[voicebm] • dashboard port already updated or not found")
except Exception as e:
    print(f"[voicebm] ERROR fixing dashboard port: {e}")

# ---------------------------------------------------------------------------
# 2. Fix add_active_to_gallery
#    Bug: pending.json is a plain list but code calls .get('entries')
#    Solution: Reuse the enroll flow by publishing to voicebm/pending_active/enroll
#    The backend handles both new person creation and gallery additions the same way
# ---------------------------------------------------------------------------

m = re.search(
    r"(@app\.route\('/api/active/add_to_gallery'.*?)\n(@app\.route)",
    src,
    re.DOTALL,
)
if m:
    old_gallery = m.group(1)
    new_gallery = """\
@app.route('/api/active/add_to_gallery', methods=['POST'])
def add_active_to_gallery():
    \"\"\"Add most recent pending sample to an existing person's gallery via MQTT.\"\"\"
    try:
        data = request.get_json()
        person_id = data.get('person_id')

        if not person_id:
            return jsonify({'error': 'Missing person_id'}), 400

        person_dir = Path(ENROLL_DIR) / person_id
        if not person_dir.exists():
            return jsonify({'error': f'Person \"{person_id}\" not found'}), 404

        meta_file = person_dir / 'metadata.json'
        display_name = person_id.replace('_', ' ').title()
        if meta_file.exists():
            with open(meta_file) as f:
                display_name = json.load(f).get('display_name', display_name)

        if not Path(PENDING_FILE).exists():
            return jsonify({'error': 'No recent samples available'}), 404

        with open(PENDING_FILE) as f:
            pending_data = json.load(f)

        entries = pending_data if isinstance(pending_data, list) else pending_data.get('entries', [])
        if not entries:
            return jsonify({'error': 'No recent samples available'}), 404

        most_recent = entries[-1]
        pending_id = most_recent['id']
        emb_src = Path(PENDING_RECORDINGS).parent / 'embeddings' / f'{pending_id}.txt'
        wav_src = Path(PENDING_RECORDINGS) / f'{pending_id}.wav'

        if not wav_src.exists() or not emb_src.exists():
            return jsonify({'error': 'Sample files not found'}), 404

        payload = json.dumps({'id': pending_id, 'person_id': person_id, 'display_name': display_name})
        publish_to_mqtt('voicebm/pending_active/enroll', payload, qos=1, retain=False)
        return jsonify({'success': True, 'person_id': person_id})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

"""
    src = src.replace(old_gallery, new_gallery, 1)
    print("[voicebm] Patched: add_active_to_gallery")
else:
    print("[voicebm] WARNING: add_active_to_gallery not found", file=sys.stderr)

# ---------------------------------------------------------------------------
# 3. Fix train_active_as_person
#    Bug: pending.json is a plain list but code calls .get('entries')
#    Original: creates NEW person with metadata and copies files
#    Our approach: validate name, delegate to stt_service via MQTT to create person
# ---------------------------------------------------------------------------

m2 = re.search(
    r"(@app\.route\('/api/active/train_as_person'.*?)\n(@app\.route)",
    src,
    re.DOTALL,
)
if m2:
    old_train = m2.group(1)
    new_train = """\
@app.route('/api/active/train_as_person', methods=['POST'])
def train_active_as_person():
    \"\"\"Enroll most recent pending sample as a new person via MQTT.\"\"\"
    try:
        data = request.get_json()
        person_name = data.get('person_name', '').strip()

        if not person_name:
            return jsonify({'error': 'Missing person_name'}), 400

        is_valid, error_msg = validate_person_name(person_name)
        if not is_valid:
            return jsonify({'error': error_msg}), 400

        person_id = normalize_person_id(person_name)
        
        # Check if person already exists
        person_dir = Path(ENROLL_DIR) / person_id
        if person_dir.exists():
            return jsonify({'error': f'Person \"{person_name}\" already exists (normalized as \"{person_id}\")'}), 400

        if not Path(PENDING_FILE).exists():
            return jsonify({'error': 'No recent samples available'}), 404

        with open(PENDING_FILE) as f:
            pending_data = json.load(f)

        entries = pending_data if isinstance(pending_data, list) else pending_data.get('entries', [])
        if not entries:
            return jsonify({'error': 'No recent samples available'}), 404

        most_recent = entries[-1]
        pending_id = most_recent['id']

        payload = json.dumps({'id': pending_id, 'person_id': person_id, 'display_name': person_name})
        publish_to_mqtt('voicebm/pending_active/enroll', payload, qos=1, retain=False)
        return jsonify({'success': True, 'person_id': person_id})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

"""
    src = src.replace(old_train, new_train, 1)
    print("[voicebm] Patched: train_active_as_person")
else:
    print("[voicebm] WARNING: train_active_as_person not found", file=sys.stderr)

# ---------------------------------------------------------------------------
# 4. Fix voicebm_stt_service.py hardcoded audio URL
#    Template has: "audio_url": f"http://10.50.60.58:9090/pending/{pending_id}.wav",
#    Must replace with value from config.json
# ---------------------------------------------------------------------------

STT_SERVICE = "/app/voicebm_stt_service.py"

try:
    with open(CONFIG_FILE, 'r') as f:
        config = json.load(f)
    audio_base_url = config.get('audio_server', {}).get('base_url', 'http://10.50.60.58:9090')
    print(f"[voicebm] Audio base URL from config: {audio_base_url}")
except Exception as e:
    print(f"[voicebm] WARNING: Could not load config for audio_url: {e}")
    audio_base_url = 'http://10.50.60.58:9090'

if Path(STT_SERVICE).exists():
    try:
        with open(STT_SERVICE, 'r') as f:
            stt_content = f.read()
        
        # Replace hardcoded audio URL
        old_url = '"audio_url": f"http://10.50.60.58:9090/pending/{pending_id}.wav",'
        new_url = f'"audio_url": f"{audio_base_url}/pending/{{pending_id}}.wav",'
        
        if old_url in stt_content:
            stt_content = stt_content.replace(old_url, new_url, 1)
            with open(STT_SERVICE, 'w') as f:
                f.write(stt_content)
            print(f"[voicebm] ✓ Fixed voicebm_stt_service.py audio_url to {audio_base_url}")
        else:
            print("[voicebm] • voicebm_stt_service.py audio_url already updated or not found")
    except Exception as e:
        print(f"[voicebm] ERROR fixing voicebm_stt_service.py audio_url: {e}")
else:
    print(f"[voicebm] WARNING: {STT_SERVICE} not found")

# ---------------------------------------------------------------------------
# 5. Audio URLs now use config.json values - no proxy routes needed
# ---------------------------------------------------------------------------
print("[voicebm] Audio URL patching complete")

open(DASHBOARD, "w").write(src)
print("[voicebm] Dashboard patching complete")
