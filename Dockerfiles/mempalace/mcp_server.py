#!/usr/bin/env python3
"""
MemPalace MCP Server - Exposes mempalace to Home Assistant and other MCP clients
Supports both HTTP REST API and MCP protocol via Server-Sent Events (SSE)
"""

import os
import subprocess
import sys
import argparse
import asyncio
import json
from pathlib import Path
from datetime import datetime
from typing import Optional

# Palace configuration
PALACE_DIR = os.getenv('PALACE_DIR', '/data/palace')
Path(PALACE_DIR).mkdir(parents=True, exist_ok=True)

def run_mempalace_cmd(cmd_args: list) -> dict:
    """Run a mempalace command and return output"""
    try:
        result = subprocess.run(
            ['mempalace'] + cmd_args,
            cwd=PALACE_DIR,
            capture_output=True,
            text=True,
            timeout=60
        )
        return {
            'success': result.returncode == 0,
            'stdout': result.stdout.strip(),
            'stderr': result.stderr.strip(),
            'returncode': result.returncode
        }
    except subprocess.TimeoutExpired:
        return {'success': False, 'error': 'Command timeout', 'returncode': -1}
    except Exception as e:
        return {'success': False, 'error': str(e), 'returncode': -1}

def search_memory(query: str) -> str:
    """Search the memory palace"""
    if not query:
        return "Error: Missing query"
    result = run_mempalace_cmd(['search', query])
    if result['success']:
        return f"Search results for '{query}':\n\n{result['stdout']}"
    else:
        return f"Search failed: {result.get('error', result.get('stderr', 'Unknown error'))}"

def store_memory(wing: str, hall: str, room: str, content: str) -> str:
    """Store a memory in the palace"""
    if not content:
        return "Error: Missing content"
    wing = wing or "home_assistant"
    hall = hall or "memories"
    room = room or "stored"
    memory_dir = Path(PALACE_DIR) / "stored_memories"
    memory_dir.mkdir(exist_ok=True)
    memory_file = memory_dir / f"{wing}_{hall}_{room}.md"
    timestamp = datetime.now().isoformat()
    with open(memory_file, 'a') as f:
        f.write(f"\n## {timestamp}\n{content}\n")
    return f"✓ Memory stored in: {wing}/{hall}/{room}"

def get_context(wing: str = "") -> str:
    """Get wake-up context"""
    cmd = ['wake-up']
    if wing:
        cmd.extend(['--wing', wing])
    result = run_mempalace_cmd(cmd)
    if result['success']:
        return result['stdout']
    else:
        return f"Error retrieving context: {result.get('error', result.get('stderr'))}"

def palace_status() -> str:
    """Get palace status"""
    result = run_mempalace_cmd(['status'])
    if result['success']:
        return result['stdout']
    else:
        return "Palace not initialized. Run: mempalace init <dir>"

async def run_http_server(port: int = 3001):
    """Run HTTP server for HA and testing"""
    from fastapi import FastAPI, Response
    from fastapi.responses import StreamingResponse
    import uvicorn
    
    app = FastAPI(title="MemPalace MCP Server")
    
    # MCP Tool Definitions
    MCP_TOOLS = [
        {
            "name": "search_memory",
            "description": "Search the memory palace for relevant context",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"}
                },
                "required": ["query"]
            }
        },
        {
            "name": "store_memory",
            "description": "Store a memory in the palace (wing/hall/room)",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "wing": {"type": "string", "description": "e.g., 'home_automation'"},
                    "hall": {"type": "string", "description": "e.g., 'lights'"},
                    "room": {"type": "string", "description": "e.g., 'office_light'"},
                    "content": {"type": "string", "description": "Memory content"}
                },
                "required": ["wing", "hall", "room", "content"]
            }
        },
        {
            "name": "get_context",
            "description": "Get wake-up context for a wing",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "wing": {"type": "string", "description": "Wing name (optional)"}
                },
                "properties": {}
            }
        },
        {
            "name": "palace_status",
            "description": "Get current palace status and statistics",
            "inputSchema": {
                "type": "object",
                "properties": {}
            }
        }
    ]
    
    async def sse_generator():
        """Generate MCP protocol messages as SSE stream"""
        # Send initialization message
        yield f"event: message\ndata: {json.dumps({'type': 'initialize', 'protocolVersion': '2024-11-05'})}\n\n"
        
        # Send tool list
        tools_msg = {
            "type": "resources/list",
            "resources": []
        }
        yield f"event: message\ndata: {json.dumps(tools_msg)}\n\n"
        
        # Keep connection alive - wait for client requests
        # In a real implementation, this would handle incoming SSE client messages
        try:
            while True:
                await asyncio.sleep(30)
        except asyncio.CancelledError:
            pass
    
    @app.get("/mcp/sse")
    async def sse_endpoint():
        """MCP protocol endpoint via Server-Sent Events for HA MCP client"""
        return StreamingResponse(
            sse_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no"
            }
        )
    
    @app.get("/mcp/tools")
    async def list_tools():
        """List all available MCP tools"""
        return {"tools": MCP_TOOLS}
    
    # Existing HTTP REST endpoints (keep for backward compatibility)
    @app.post("/mcp/tools/search_memory")
    async def api_search(request: dict):
        result = search_memory(request.get("query", ""))
        return {"result": result}
    
    @app.post("/mcp/tools/store_memory")
    async def api_store(request: dict):
        result = store_memory(
            request.get("wing", ""),
            request.get("hall", ""),
            request.get("room", ""),
            request.get("content", "")
        )
        return {"result": result}
    
    @app.get("/mcp/tools/get_context")
    async def api_context(wing: str = ""):
        result = get_context(wing)
        return {"result": result}
    
    @app.get("/mcp/tools/palace_status")
    async def api_status():
        result = palace_status()
        return {"result": result}
    
    @app.get("/mcp/health")
    async def api_health():
        return {"status": "ok", "service": "mempalace-mcp"}
    
    @app.get("/mcp")
    async def mcp_http_root():
        """HTTP MCP protocol root endpoint - returns tool list for Copilot HTTP client"""
        return {
            "tools": MCP_TOOLS
        }
    
    @app.post("/mcp")
    async def mcp_http_call(request: dict):
        """HTTP MCP protocol - handle tool calls"""
        tool_name = request.get("tool", request.get("name"))
        tool_input = request.get("input", request.get("arguments", {}))
        
        if tool_name == "search_memory":
            result = search_memory(tool_input.get("query", ""))
        elif tool_name == "store_memory":
            result = store_memory(
                tool_input.get("wing", ""),
                tool_input.get("hall", ""),
                tool_input.get("room", ""),
                tool_input.get("content", "")
            )
        elif tool_name == "get_context":
            result = get_context(tool_input.get("wing", ""))
        elif tool_name == "palace_status":
            result = palace_status()
        else:
            return {"error": f"Unknown tool: {tool_name}"}, 400
        
        return {"result": result}
    
    @app.get("/")
    async def api_root():
        return {
            "service": "MemPalace MCP Server",
            "version": "1.0.0",
            "endpoints": {
                "mcp_sse": "GET /mcp/sse (for HA MCP client)",
                "tools_list": "GET /mcp/tools",
                "search": "POST /mcp/tools/search_memory",
                "store": "POST /mcp/tools/store_memory",
                "context": "GET /mcp/tools/get_context",
                "status": "GET /mcp/tools/palace_status",
                "health": "GET /mcp/health"
            }
        }
    
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info")
    server_instance = uvicorn.Server(config)
    await server_instance.serve()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MemPalace MCP Server")
    parser.add_argument("--http", type=int, help="HTTP port", metavar="PORT", default=3001)
    args = parser.parse_args()
    try:
        print(f"Starting MemPalace MCP HTTP server on port {args.http}")
        asyncio.run(run_http_server(args.http))
    except KeyboardInterrupt:
        print("\nServer stopped")
        sys.exit(0)
