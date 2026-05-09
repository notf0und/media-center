#!/usr/bin/env python3
"""
MemPalace HTTP wrapper - REST API for the mempalace CLI
"""

import os
import json
import subprocess
import sys
from pathlib import Path
from flask import Flask, request, jsonify, send_from_directory, Response

app = Flask(__name__, static_folder='static', static_url_path='/static')

# MemPalace data directory
PALACE_DIR = os.getenv('PALACE_DIR', '/data/palace')
Path(PALACE_DIR).mkdir(parents=True, exist_ok=True)

# Command timeout in seconds (configurable via env var, default 10 minutes for mining large datasets)
CMD_TIMEOUT = int(os.getenv('CMD_TIMEOUT', '600'))

def run_mempalace_cmd(cmd_args):
    """Run a mempalace command and return output"""
    try:
        # --palace flag must come BEFORE the subcommand
        cmd = ['mempalace', '--palace', PALACE_DIR] + cmd_args
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=CMD_TIMEOUT
        )
        return {
            'success': result.returncode == 0,
            'stdout': result.stdout,
            'stderr': result.stderr,
            'returncode': result.returncode
        }
    except subprocess.TimeoutExpired:
        return {
            'success': False,
            'error': 'Command timeout',
            'returncode': -1
        }
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'returncode': -1
        }

# Web UI Routes
@app.route('/', methods=['GET'])
def index():
    """Serve the web UI"""
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/ui', methods=['GET'])
def ui():
    """Serve the web UI (alternate endpoint)"""
    return send_from_directory(app.static_folder, 'index.html')

# API Routes
@app.route('/api/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({
        'status': 'ok',
        'service': 'mempalace',
        'palace_dir': PALACE_DIR,
        'palace_exists': os.path.exists(PALACE_DIR)
    })

@app.route('/status', methods=['GET'])
def status():
    """Show what's been filed in the palace"""
    result = run_mempalace_cmd(['status'])
    return jsonify(result)

@app.route('/search', methods=['GET', 'POST'])
def search():
    """Search the palace
    
    Query string: GET /search?q=your+query
    JSON body: POST /search with {"query": "your query"}
    """
    if request.method == 'GET':
        query = request.args.get('q', '')
    else:
        data = request.get_json() or {}
        query = data.get('query', '')
    
    if not query:
        return jsonify({'error': 'Missing query parameter'}), 400
    
    result = run_mempalace_cmd(['search', query])
    return jsonify({
        **result,
        'query': query
    })

@app.route('/wake-up', methods=['GET'])
def wake_up():
    """Get L0 + L1 wake-up context for the palace
    
    Optional: ?wing=project_name for specific wing
    """
    wing = request.args.get('wing')
    cmd = ['wake-up']
    if wing:
        cmd.extend(['--wing', wing])
    
    result = run_mempalace_cmd(cmd)
    return jsonify({
        **result,
        'wing': wing or 'all'
    })

@app.route('/init', methods=['POST'])
def init():
    """Initialize palace by detecting rooms from folder structure
    
    JSON body: {"source_dir": "/path/to/scan"} (optional, defaults to PALACE_DIR)
    """
    data = request.get_json() or {}
    source_dir = data.get('source_dir', PALACE_DIR)
    
    try:
        # --palace flag must come BEFORE the subcommand
        cmd = ['mempalace', '--palace', PALACE_DIR, 'init', source_dir]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            input='\n',  # Send Enter to accept defaults
            timeout=CMD_TIMEOUT
        )
        return jsonify({
            'success': result.returncode == 0,
            'stdout': result.stdout,
            'stderr': result.stderr,
            'returncode': result.returncode,
            'source_dir': source_dir
        })
    except subprocess.TimeoutExpired:
        return jsonify({'error': 'Initialization timeout', 'returncode': -1}), 504
    except Exception as e:
        return jsonify({'error': str(e), 'returncode': -1}), 500

@app.route('/browse', methods=['GET'])
def browse():
    """List directory contents for file browser
    
    Query params:
    - path: directory path to browse (default: /root)
    - filter: optional search filter for filenames
    """
    path = request.args.get('path', '/root')
    filter_term = request.args.get('filter', '').lower()
    
    try:
        # Ensure path exists and is a directory
        p = Path(path)
        if not p.exists():
            return jsonify({'error': f'Path does not exist: {path}'}), 404
        if not p.is_dir():
            return jsonify({'error': f'Path is not a directory: {path}'}), 400
        
        # List directory contents
        items = []
        try:
            for item in sorted(p.iterdir()):
                # Skip hidden files unless we're at /root level
                if item.name.startswith('.') and path != '/root':
                    continue
                
                # Apply filter if provided
                if filter_term and filter_term not in item.name.lower():
                    continue
                
                items.append({
                    'name': item.name,
                    'path': str(item),
                    'is_dir': item.is_dir(),
                    'is_file': item.is_file(),
                })
        except PermissionError:
            return jsonify({'error': f'Permission denied: {path}'}), 403
        
        return jsonify({
            'success': True,
            'path': str(p),
            'parent': str(p.parent) if p != p.parent else None,
            'items': items,
            'count': len(items)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/mine', methods=['POST'])
def mine():
    """Mine project files or conversations into the palace (streaming via SSE)
    
    JSON body: {
        "source_dir": "/path/to/mine",
        "mode": "projects|convos",
        "wing": "optional_wing_name"
    }
    mode defaults to "projects"
    """
    data = request.get_json() or {}
    source_dir = data.get('source_dir')
    mode = data.get('mode', 'projects')
    wing = data.get('wing')
    
    if not source_dir:
        return jsonify({'error': 'Missing source_dir parameter'}), 400
    
    def stream_mine():
        """Stream mining progress via SSE"""
        try:
            cmd = ['mempalace', '--palace', PALACE_DIR, 'mine', source_dir]
            if mode == 'convos':
                cmd.extend(['--mode', 'convos'])
            if wing:
                cmd.extend(['--wing', wing])
            
            # Start the mining process
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )
            
            # Stream output line by line
            for line in iter(process.stdout.readline, ''):
                if line:
                    # Escape newlines for SSE
                    escaped_line = line.rstrip('\n').replace('\n', '\\n')
                    yield f"data: {json.dumps({'line': escaped_line})}\n\n"
            
            # Wait for process to complete
            process.wait()
            
            # Send completion status
            if process.returncode == 0:
                yield f"data: {json.dumps({'status': 'complete', 'success': True})}\n\n"
            else:
                yield f"data: {json.dumps({'status': 'complete', 'success': False, 'returncode': process.returncode})}\n\n"
                
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
    
    return Response(stream_mine(), mimetype='text/event-stream')

@app.route('/mcp', methods=['POST'])
def mcp_bridge():
    """HTTP bridge for MCP protocol - forwards requests to mempalace-mcp stdio server"""
    try:
        # Get request body (MCP JSON-RPC requests)
        data = request.get_json() or {}
        
        # Run mempalace-mcp as subprocess and pipe the request through stdin
        process = subprocess.Popen(
            ['mempalace-mcp', '--palace', PALACE_DIR],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        # Send request to stdin and get response from stdout
        stdout, stderr = process.communicate(
            input=json.dumps(data),
            timeout=CMD_TIMEOUT
        )
        
        if process.returncode != 0:
            return jsonify({
                'error': f'MCP server error: {stderr}',
                'returncode': process.returncode
            }), 500
        
        # Parse and return MCP response
        response = json.loads(stdout) if stdout else {}
        return jsonify(response)
        
    except subprocess.TimeoutExpired:
        return jsonify({'error': 'MCP server timeout'}), 504
    except json.JSONDecodeError as e:
        return jsonify({'error': f'Invalid JSON response: {str(e)}'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/version', methods=['GET'])
def version():
    """Get mempalace version from pip"""
    import importlib.metadata
    try:
        version_str = importlib.metadata.version('mempalace')
    except Exception:
        version_str = 'unknown'
    return jsonify({'version': version_str})

@app.route('/delete-palace', methods=['POST'])
def delete_palace():
    """Delete all mined data from the palace"""
    try:
        import shutil
        import time
        import subprocess
        
        palace_path = Path(PALACE_DIR)
        
        # Strategy: Empty the directory instead of deleting/recreating it.
        # This avoids inode locks that prevent rmtree when processes have handles open.
        if palace_path.exists() and palace_path.is_dir():
            for item in palace_path.iterdir():
                try:
                    if item.is_dir():
                        shutil.rmtree(item, ignore_errors=True)
                    else:
                        item.unlink()
                except Exception as item_err:
                    pass  # Continue even if individual items fail
        
        # Close any open database connections
        try:
            import gc
            gc.collect()
        except:
            pass
        
        return jsonify({
            'success': True,
            'message': 'Palace data deleted successfully',
            'palace_dir': PALACE_DIR
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
