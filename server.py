import os
import sys
import json
import logging
import asyncio
import uvicorn
from typing import Any, List
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

# Add the mempalace submodule root to sys.path so we can import the 'mempalace' package
submodule_path = os.path.join(os.path.dirname(__file__), "mempalace")
if submodule_path not in sys.path:
    sys.path.insert(0, submodule_path)

from mcp.server import Server # noqa: E402
from mcp.server.sse import SseServerTransport # noqa: E402
from mcp.types import Tool, TextContent # noqa: E402

# Import core MemPalace logic (from vendored package)
from mempalace.mcp_server import ( # noqa: E402
    tool_status, tool_list_wings, tool_search, tool_kg_query, tool_kg_add, tool_kg_timeline
)

# Configuration
PORT_API = int(os.getenv("PORT_API", "8000"))
PORT_DASHBOARD = int(os.getenv("PORT_DASHBOARD", "8080"))

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("mempalace-server")

# Silence noisy uvicorn access logs
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

# 1. Initialize MCP Server
mcp_server = Server("mempalace-server")

# Register Tools
@mcp_server.list_tools()
async def list_tools() -> List[Tool]:
    """List available MemPalace tools."""
    return [
        Tool(name="mempalace_status", description="Palace overview + AAAK spec", inputSchema={"type": "object"}),
        Tool(name="mempalace_list_wings", description="List memory wings with document counts", inputSchema={"type": "object"}),
        Tool(name="mempalace_search", description="Semantic search across all stored memories", inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "n_results": {"type": "integer", "description": "Number of results to return", "default": 5}
            },
            "required": ["query"]
        }),
        Tool(name="mempalace_kg_query", description="Query the knowledge graph for an entity and its relationships", inputSchema={
            "type": "object",
            "properties": {
                "entity": {"type": "string", "description": "Entity name to look up"},
                "as_of": {"type": "string", "description": "Optional ISO date to query historical state"},
                "direction": {"type": "string", "enum": ["outgoing", "incoming", "both"], "default": "both"}
            },
            "required": ["entity"]
        }),
        Tool(name="mempalace_kg_add", description="Add facts or observations to the knowledge graph", inputSchema={
            "type": "object",
            "properties": {
                "subject": {"type": "string", "description": "Subject entity"},
                "predicate": {"type": "string", "description": "Relationship predicate"},
                "object": {"type": "string", "description": "Object entity or value"},
                "started": {"type": "string", "description": "Optional ISO date the fact became true"}
            },
            "required": ["subject", "predicate", "object"]
        }),
        Tool(name="add_observations", description="Alias for mempalace_kg_add — add facts to the knowledge graph", inputSchema={
            "type": "object",
            "properties": {
                "subject": {"type": "string"},
                "predicate": {"type": "string"},
                "object": {"type": "string"},
                "started": {"type": "string"}
            },
            "required": ["subject", "predicate", "object"]
        }),
    ]

@mcp_server.call_tool()
async def call_tool(name: str, arguments: Any) -> List[TextContent]:
    """Execute a MemPalace tool."""
    # Mapping table for simplicity 
    tool_map = {
        "mempalace_status": tool_status,
        "mempalace_list_wings": tool_list_wings,
        "mempalace_kg_query": lambda args: tool_kg_query(**args),
        "mempalace_search": lambda args: tool_search(**args),
        "add_observations": lambda args: tool_kg_add(**args), # Alias for compatibility
        "mempalace_kg_add": lambda args: tool_kg_add(**args),
    }
    
    if name not in tool_map:
        logger.warning(f"⚠️ Tool rejected: '{name}' not supported by bridge.")
        return [TextContent(type="text", text=f"Error: Tool '{name}' not supported by bridge.")]
    
    try:
        logger.info(f"🔨 Executing tool: {name} | args: {json.dumps(arguments)}")
        result = tool_map[name](arguments)
        logger.info(f"✅ Tool {name} completed successfully")
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    except Exception as e:
        logger.error(f"Tool execution failed: {e}")
        return [TextContent(type="text", text=f"Execution error: {str(e)}")]

# ---------------------------------------------------------
# 2. FastAPI Setup - MCP API (Port 8000)
# ---------------------------------------------------------
mcp_app = FastAPI(title="MemPalace MCP API", redirect_slashes=False)
# Starlette 1.0 mount() only matches paths with a trailing slash component,
# so the transport endpoint must also use the trailing slash so clients POST
# to /messages/?session_id=... which routes correctly to the mounted ASGI app.
sse_transport = SseServerTransport("/messages/")

mcp_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@mcp_app.get("/")
async def root():
    return {"status": "ok", "service": "mcp-api"}

@mcp_app.get("/sse")
async def sse_endpoint(request: Request):
    """MCP SSE endpoint for agent communication."""
    if request.headers.get("X-Health-Check"):
        return JSONResponse({"status": "ready", "mcp": "sse"})

    async with sse_transport.connect_sse(
        request.scope, request.receive, request._send
    ) as (read_stream, write_stream):
        await mcp_server.run(
            read_stream,
            write_stream,
            mcp_server.create_initialization_options(),
        )

# Mount as a raw ASGI app so handle_post_message sends its own 202 without
# FastAPI adding a second response on return (which causes "response already
# completed" errors).
mcp_app.mount("/messages/", app=sse_transport.handle_post_message)

# ---------------------------------------------------------
# 3. FastAPI Setup - Visualization Dashboard (Port 8080)
# ---------------------------------------------------------
viz_app = FastAPI(title="MemPalace Visualization Dashboard")

viz_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@viz_app.get("/api/graph")
async def get_graph():
    """Retrieve the full Knowledge Graph for the dashboard."""
    try:
        timeline = tool_kg_timeline()
        cy_data = {"nodes": [], "edges": []}
        entities = set()
        
        for fact in timeline.get("timeline", []):
            subj = fact.get("subject")
            obj = fact.get("object")
            pred = fact.get("predicate")
            
            if subj and subj not in entities:
                cy_data["nodes"].append({"data": {"id": subj, "label": subj, "type": "entity"}})
                entities.add(subj)
            if obj and obj not in entities:
                cy_data["nodes"].append({"data": {"id": obj, "label": obj, "type": "entity"}})
                entities.add(obj)
            
            if subj and obj:
                cy_data["edges"].append({
                    "data": {
                        "source": subj,
                        "target": obj,
                        "label": pred
                    }
                })
            
        return cy_data
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

# Serve Dashboard static files
dashboard_path = os.path.join(os.path.dirname(__file__), "dashboard")
if os.path.exists(dashboard_path):
    viz_app.mount("/", StaticFiles(directory=dashboard_path, html=True), name="dashboard")

@viz_app.get("/health")
async def health():
    return {"status": "ok", "service": "dashboard"}

# ---------------------------------------------------------
# 4. Multi-Server Startup
# ---------------------------------------------------------
async def start_servers():
    """Run both API and Visualization servers in parallel."""
    config_api = uvicorn.Config(mcp_app, host="0.0.0.0", port=PORT_API, log_level="info")
    config_viz = uvicorn.Config(viz_app, host="0.0.0.0", port=PORT_DASHBOARD, log_level="info")
    
    server_api = uvicorn.Server(config_api)
    server_viz = uvicorn.Server(config_viz)
    
    logger.info(f"Starting MCP API on port {PORT_API}")
    logger.info(f"Starting Visualization Dashboard on port {PORT_DASHBOARD}")
    
    await asyncio.gather(
        server_api.serve(),
        server_viz.serve()
    )

if __name__ == "__main__":
    try:
        asyncio.run(start_servers())
    except KeyboardInterrupt:
        logger.info("Server stopped by user")

