import pytest
import httpx
from server import app

# We use anyio to support async tests with timeouts
@pytest.fixture
def anyio_backend():
    return "asyncio"

@pytest.mark.anyio
async def test_root_endpoint():
    """Verify that the root endpoint is alive."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/")
        assert response.status_code == 200
        assert "MemPalace Viz Service" in response.text

@pytest.mark.anyio
async def test_dashboard_endpoint():
    """Verify that the dashboard is served."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/dashboard/")
        assert response.status_code == 200
        assert "cytoscape" in response.text

@pytest.mark.anyio
async def test_graph_api_structure():
    """Verify the /api/graph returns the correct JSON format."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/graph")
        assert response.status_code == 200
        data = response.json()
        assert "nodes" in data
        assert "edges" in data

@pytest.mark.anyio
async def test_mcp_sse_handshake():
    """Verify that the SSE endpoint is correctly mapped and responsive."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # Use a health-check header to verify the route without hitting the infinite loop
        response = await client.get("/sse", headers={"X-Health-Check": "true"})
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"
        assert data["mcp"] == "sse"
