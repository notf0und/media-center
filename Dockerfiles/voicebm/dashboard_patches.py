"""
Post-fill patches for voicebm_dashboard.py.
Fixes bugs in VoiceBM's dashboard that are incompatible with our Docker setup.
Run by entrypoint.sh after fill_template() completes.
"""
import sys
import re
from pathlib import Path

DASHBOARD = "/app/voicebm_dashboard.py"


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

# ---------------------------------------------------------------------------
# 1. Fix add_active_to_gallery
#    Bug: pending.json is a plain list but code calls .get('entries')
#    Bug: entries have no audio_path/emb_path — derive paths from entry id
#    Fix: read list directly, derive paths, delegate to stt_service via MQTT
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
# 2. Fix train_active_as_person
#    Same bugs as add_active_to_gallery — fix pending.json handling and paths,
#    delegate enrollment to stt_service via MQTT.
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
# 3. Fix audio URLs to use relative paths (browser-portable)
#    Change: http://10.50.60.58:9090/pending/{id}.wav
#    To:     /pending/{id}.wav
#    This allows URLs to work regardless of host IP, domain, or proxy setup
# ---------------------------------------------------------------------------

STT_SERVICE = "/app/voicebm_stt_service.py"
stt_src = open(STT_SERVICE).read()
stt_src = stt_src.replace(
    '"audio_url": f"/api/audio/pending/{pending_id}.wav",',
    '"audio_url": f"/pending/{pending_id}.wav",',
    1
)
open(STT_SERVICE, "w").write(stt_src)
print("[voicebm] Patched: voicebm_stt_service.py audio_url to /pending proxy")

AUDIO_SERVER = "/app/audio_server.py"
if open(AUDIO_SERVER).read().find("10.50.60.58") >= 0:
    audio_src = open(AUDIO_SERVER).read()
    audio_src = audio_src.replace(
        '        print(f"  http://10.50.60.58:{PORT}/living/living_20251128_120000.wav")',
        '        print(f"  /living/living_20251128_120000.wav")',
        1
    )
    audio_src = audio_src.replace(
        '        print(f"  http://10.50.60.58:{PORT}/pending/active_1732825200000.wav")',
        '        print(f"  /pending/active_1732825200000.wav")',
        1
    )
    open(AUDIO_SERVER, "w").write(audio_src)
    print("[voicebm] Patched: audio_server.py example URLs to relative paths")

# ---------------------------------------------------------------------------
# 4. Add audio proxy routes for /pending/ and /api/audio/
#    Both proxy to audio_server on port 9090
#    /pending/{file} is for backward compatibility and direct browser access
#    /api/audio/{path} is for programmatic/API access
# ---------------------------------------------------------------------------

audio_proxy = '''
@app.route('/pending/<path:filepath>')
def proxy_pending(filepath):
    """Proxy /pending/ requests to the audio server on port 9090"""
    import urllib.request
    url = f"http://localhost:9090/pending/{filepath}"
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            content_type = response.headers.get('content-type', 'audio/wav')
            return app.response_class(
                response.read(),
                content_type=content_type,
                status=response.status
            )
    except Exception as e:
        return jsonify({'error': f'Audio proxy error: {str(e)}'}), 500

@app.route('/api/audio/<path:filepath>')
def proxy_audio(filepath):
    """Proxy /api/audio/ requests to the audio server on port 9090"""
    import urllib.request
    url = f"http://localhost:9090/{filepath}"
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            content_type = response.headers.get('content-type', 'audio/wav')
            return app.response_class(
                response.read(),
                content_type=content_type,
                status=response.status
            )
    except Exception as e:
        return jsonify({'error': f'Audio proxy error: {str(e)}'}), 500

'''

# Insert before "if __name__"
if_main_pos = src.find('\nif __name__')
if if_main_pos > 0:
    src = src[:if_main_pos] + '\n' + audio_proxy + src[if_main_pos:]
    print("[voicebm] Added: /pending/<file> and /api/audio/<path> proxy routes")
else:
    print("[voicebm] WARNING: could not find 'if __name__' insertion point", file=sys.stderr)

open(DASHBOARD, "w").write(src)
print("[voicebm] Dashboard patching complete")
