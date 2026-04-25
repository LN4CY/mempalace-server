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
from mempalace.mcp_server import TOOLS # noqa: E402

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
    """List available MemPalace tools dynamically from the core registry."""
    tools_list = []
    for name, config in TOOLS.items():
        tools_list.append(Tool(
            name=name,
            description=config["description"],
            inputSchema=config["input_schema"]
        ))
    
    # Add alias for backwards compatibility with older prompts
    tools_list.append(Tool(
        name="add_observations",
        description="Alias for mempalace_kg_add — add facts to the knowledge graph",
        inputSchema=TOOLS["mempalace_kg_add"]["input_schema"]
    ))
    return tools_list

@mcp_server.call_tool()
async def call_tool(name: str, arguments: Any) -> List[TextContent]:
    """Execute a MemPalace tool dynamically."""
    
    # Resolve alias
    if name == "add_observations":
        name = "mempalace_kg_add"
        
    if name not in TOOLS:
        logger.warning(f"⚠️ Tool rejected: '{name}' not supported by bridge.")
        return [TextContent(type="text", text=f"Error: Tool '{name}' not supported by bridge.")]
    
    # Coerce arguments if necessary (similar to core mcp_server logic)
    schema_props = TOOLS[name]["input_schema"].get("properties", {})
    tool_args = {k: v for k, v in arguments.items() if k in schema_props}
    
    for key, value in list(tool_args.items()):
        prop_schema = schema_props.get(key, {})
        declared_type = prop_schema.get("type")
        try:
            if declared_type == "integer" and not isinstance(value, int):
                tool_args[key] = int(value)
            elif declared_type == "number" and not isinstance(value, (int, float)):
                tool_args[key] = float(value)
        except (ValueError, TypeError):
            return [TextContent(type="text", text=f"Invalid value for parameter '{key}'")]
    
    try:
        logger.info(f"🔨 Executing tool: {name} | args: {json.dumps(tool_args)}")
        result = TOOLS[name]["handler"](**tool_args)
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
        timeline = TOOLS["mempalace_kg_timeline"]["handler"]()
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
    config_api = uvicorn.Config(mcp_app, host="0.0.0.0", port=PORT_API, log_level="info", access_log=False)
    config_viz = uvicorn.Config(viz_app, host="0.0.0.0", port=PORT_DASHBOARD, log_level="info", access_log=False)
    
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

