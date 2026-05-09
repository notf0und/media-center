#!/usr/bin/env python3
"""
Automatic Муз-ТВ stream link updater
Fetches the current stream URL from glaz.tv and updates streams.yaml
"""

import json
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote

import requests
import yaml
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Configuration
GLAZ_TV_URL = "https://glaz.tv/online-tv/muz-tv"
SCRIPTS_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPTS_DIR.parent
STREAMS_YAML = PROJECT_ROOT / "streams.yaml"
DOCKER_COMPOSE_FILE = PROJECT_ROOT / "docker-compose.yml"
STREAM_NAME = "Муз-ТВ"
LOG_FILE = PROJECT_ROOT / "tmp" / "muztv_update.log"


def log(message):
    """Log message to console and file"""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    log_msg = f"[{timestamp}] {message}"
    print(log_msg)
    
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(log_msg + "\n")


def create_session_with_retries():
    """Create requests session with retry strategy"""
    session = requests.Session()
    retry_strategy = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
    })
    return session


def fetch_muztv_stream_url():
    """
    Fetch the current Муз-ТВ stream URL from glaz.tv
    Looks for m3u8 URL in page content or API responses
    """
    try:
        session = create_session_with_retries()
        log(f"Fetching stream URL from {GLAZ_TV_URL}")
        
        response = session.get(GLAZ_TV_URL, timeout=10)
        response.raise_for_status()
        
        html = response.text
        
        # Look for m3u8 URL in the page
        # Pattern for stream URL in HTML/JavaScript
        patterns = [
            r'https://[^"\'<>\s]+\.m3u8[^"\'<>\s]*',
            r'"url":"(https://[^"]+\.m3u8[^"]*)"',
            r"'url':'(https://[^']+\.m3u8[^']*)'",
            r'source["\']?\s*:\s*["\']?(https://[^\s"\']+\.m3u8[^\s"\']*)',
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, html)
            if matches:
                stream_url = matches[0]
                # Clean up if it's part of JSON
                if isinstance(stream_url, tuple):
                    stream_url = stream_url[0] if stream_url else None
                if stream_url and stream_url.endswith('.m3u8'):
                    log(f"Found stream URL: {stream_url[:100]}...")
                    return stream_url
        
        # Try to find in JavaScript data
        json_match = re.search(r'window\.data\s*=\s*({.*?});', html)
        if json_match:
            try:
                data = json.loads(json_match.group(1))
                if isinstance(data, dict):
                    stream_url = data.get('url') or data.get('stream') or data.get('src')
                    if stream_url:
                        log(f"Found stream URL in JSON: {str(stream_url)[:100]}...")
                        return stream_url
            except json.JSONDecodeError:
                pass
        
        log("ERROR: Could not extract stream URL from page")
        return None
        
    except requests.RequestException as e:
        log(f"ERROR: Failed to fetch URL: {e}")
        return None


def update_streams_yaml(new_url):
    """Update streams.yaml with new stream URL"""
    try:
        if not STREAMS_YAML.exists():
            log(f"ERROR: {STREAMS_YAML} not found")
            return False
        
        with open(STREAMS_YAML, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        
        if not isinstance(data, list):
            log("ERROR: Invalid streams.yaml format")
            return False
        
        # Find and update Муз-ТВ entry
        for stream in data:
            if stream.get('name') == STREAM_NAME:
                old_url = stream.get('stream')
                stream['stream'] = new_url
                
                # Write back to file
                with open(STREAMS_YAML, 'w', encoding='utf-8') as f:
                    yaml.dump(data, f, allow_unicode=True, default_flow_style=False)
                
                log(f"Updated streams.yaml: {STREAM_NAME}")
                log(f"Old URL: {old_url[:100] if old_url else 'N/A'}...")
                log(f"New URL: {new_url[:100]}...")
                return True
        
        log(f"ERROR: Stream '{STREAM_NAME}' not found in streams.yaml")
        return False
        
    except Exception as e:
        log(f"ERROR: Failed to update streams.yaml: {e}")
        return False


def restart_streamlink_container():
    """Restart the streamlink container via docker-compose"""
    try:
        log("Restarting streamlink container...")
        
        # Check if docker-compose file exists
        if not DOCKER_COMPOSE_FILE.exists():
            log(f"ERROR: {DOCKER_COMPOSE_FILE} not found")
            return False
        
        # Restart the container
        result = subprocess.run(
            ["docker-compose", "-f", str(DOCKER_COMPOSE_FILE), "restart", "streamlink"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode == 0:
            log("Successfully restarted streamlink container")
            return True
        else:
            log(f"ERROR: Failed to restart container: {result.stderr}")
            return False
            
    except Exception as e:
        log(f"ERROR: Failed to restart container: {e}")
        return False


def main():
    """Main execution"""
    try:
        log("Starting Муз-ТВ stream link update...")
        
        # Fetch new stream URL
        stream_url = fetch_muztv_stream_url()
        if not stream_url:
            log("FAILED: Could not fetch stream URL")
            return 1
        
        # Update streams.yaml
        if not update_streams_yaml(stream_url):
            log("FAILED: Could not update streams.yaml")
            return 1
        
        # Restart container
        if not restart_streamlink_container():
            log("WARNING: Updated streams.yaml but failed to restart container")
            return 2
        
        log("SUCCESS: Муз-ТВ stream link updated and container restarted")
        return 0
        
    except Exception as e:
        log(f"FATAL ERROR: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
