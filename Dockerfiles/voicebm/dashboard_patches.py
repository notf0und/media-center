"""
Post-fill patches for voicebm_dashboard.py.
Fixes bugs in VoiceBM's dashboard.
"""
import sys
import re

DASHBOARD = "/app/voicebm_dashboard.py"

src = open(DASHBOARD).read()

# ---------------------------------------------------------------------------
# 1. Fix add_active_to_gallery
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

open(DASHBOARD, "w").write(src)
