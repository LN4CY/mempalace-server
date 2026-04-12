import os
import sys
import json
import logging
from typing import Any, List
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
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
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mempalace-viz")

# 1. Initialize MCP Server
mcp_server = Server("mempalace-viz")

# Register Tools
@mcp_server.list_tools()
async def list_tools() -> List[Tool]:
    """List available MemPalace tools."""
    return [
        Tool(name="mempalace_status", description="Palace overview + AAAK spec", inputSchema={"type": "object"}),
        Tool(name="mempalace_list_wings", description="Wings with counts", inputSchema={"type": "object"}),
        Tool(name="mempalace_kg_query", description="Query knowledge graph", inputSchema={
            "type": "object",
            "properties": {
                "entity": {"type": "string"},
                "as_of": {"type": "string"},
                "direction": {"type": "string", "enum": ["outgoing", "incoming", "both"]}
            },
            "required": ["entity"]
        }),
        # ... (other tools will be registered similarly)
    ]

@mcp_server.call_tool()
async def call_tool(name: str, arguments: Any) -> List[TextContent]:
    """Execute a MemPalace tool."""
    # Mapping table for simplicity in this POC
    tool_map = {
        "mempalace_status": tool_status,
        "mempalace_list_wings": tool_list_wings,
        "mempalace_kg_query": lambda args: tool_kg_query(**args),
        "mempalace_search": lambda args: tool_search(**args),
        "add_observations": lambda args: tool_kg_add(**args), # Alias for compatibility
        "mempalace_kg_add": lambda args: tool_kg_add(**args),
    }
    
    if name not in tool_map:
        return [TextContent(type="text", text=f"Error: Tool '{name}' not supported by bridge.")]
    
    try:
        result = tool_map[name](arguments)
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    except Exception as e:
        logger.error(f"Tool execution failed: {e}")
        return [TextContent(type="text", text=f"Execution error: {str(e)}")]

# 2. FastAPI Setup
app = FastAPI(title="MemPalace Viz Service")
sse_transport = SseServerTransport("/sse")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/sse")
async def sse_endpoint(request: Request):
    """MCP SSE endpoint with health-check support for testing."""
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


@app.post("/messages")
async def messages_endpoint(request: Request):
    """MCP POST endpoint for SSE messages."""
    return await sse_transport.handle_post_message(
        request.scope, request.receive, request._send
    )

# 3. Visualization API
@app.get("/api/graph")
async def get_graph():
    """Retrieve the full Knowledge Graph for the dashboard."""
    try:
        # We use tool_kg_timeline to build a full graph view
        timeline = tool_kg_timeline()
        
        # Transform into Cytoscape format: {nodes: [], edges: []}
        cy_data = {"nodes": [], "edges": []}
        entities = set()
        
        # Extract entities and relations from timeline/stats
        # (Simplified logic for POC)
        for fact in timeline.get("timeline", []):
            subj = fact.get("subject")
            obj = fact.get("object")
            pred = fact.get("predicate")
            
            if subj not in entities:
                cy_data["nodes"].append({"data": {"id": subj, "label": subj, "type": "entity"}})
                entities.add(subj)
            if obj not in entities:
                cy_data["nodes"].append({"data": {"id": obj, "label": obj, "type": "entity"}})
                entities.add(obj)
            
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

# 4. Serve Dashboard
dashboard_path = os.path.join(os.path.dirname(__file__), "dashboard")
if os.path.exists(dashboard_path):
    app.mount("/dashboard", StaticFiles(directory=dashboard_path, html=True), name="dashboard")

@app.get("/", response_class=HTMLResponse)
async def root():
    return "<h1>MemPalace Viz Service</h1><p>Visit <a href='/dashboard'>/dashboard</a> for the visualization.</p>"

if __name__ == "__main__":
    import uvicorn
    logger.info(f"Starting MemPalace Viz Service on port {PORT_API}")
    uvicorn.run(app, host="0.0.0.0", port=PORT_API)
