#!/bin/bash
# Start Flask web UI and official mempalace MCP server
# Handle PUID/PGID for dynamic user creation

set -e

# Default PUID/PGID to 1000 if not set
PUID=${PUID:-1000}
PGID=${PGID:-1000}

echo "Starting MemPalace services..."
echo "[Setup] Setting UID:GID to $PUID:$PGID..."

# Create group if it doesn't exist
if ! getent group mempalace > /dev/null 2>&1; then
    groupadd -g $PGID mempalace || true
fi

# Create user if it doesn't exist
if ! getent passwd mempalace > /dev/null 2>&1; then
    useradd -m -u $PUID -g $PGID -d /home/mempalace mempalace || true
else
    # Modify existing user UID/GID to match
    usermod -u $PUID -g $PGID mempalace 2>/dev/null || true
fi

# Fix permissions on app and data directories (ignore errors on read-only mounts)
chown -R $PUID:$PGID /app /data 2>/dev/null || true

# Start Flask app in background (web UI)
echo "[Flask] Starting web UI on port 5000..."
sudo -u mempalace python /app/app.py &
FLASK_PID=$!

# Give Flask time to start
sleep 2

# Start official mempalace MCP server (stdio-based, for Copilot CLI and other MCP clients)
echo "[MCP] Starting official mempalace MCP server..."
sudo -u mempalace python -m mempalace.mcp_server --palace $PALACE_DIR &
MCP_PID=$!

# Trap signals to gracefully shut down both processes
trap "kill $FLASK_PID $MCP_PID 2>/dev/null || true" SIGTERM SIGINT

# Wait for both processes
wait