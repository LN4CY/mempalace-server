# mempalace-server

A self-contained Docker server that packages the [MemPalace](https://github.com/MemPalace/mempalace) semantic memory core and exposes it to networked AI agents over the **Model Context Protocol (MCP)** via Server-Sent Events (SSE). Includes a built-in Knowledge Graph visualization dashboard.

> **Not the same as `mempalace-viz`** — another project by that name is a pure visualization UI.
> This project is a full server deployment: MCP transport layer + mempalace core + dashboard, designed to run as a persistent service on a Raspberry Pi or any Docker host.

---

## What it does

AI agents (such as [ai-responder](https://github.com/LN4CY/ai-responder)) connect to this server over MCP-SSE and call mempalace tools directly — storing memories, querying the knowledge graph, searching past context, and writing diary entries — without needing mempalace installed locally.

```
[ AI Agent / ai-responder ]
        │
        │  MCP-SSE  (port 8000)
        ▼
[ mempalace-server ]
        ├── MCP SSE transport  (/sse + /messages)
        ├── mempalace core     (ChromaDB, KG, search, diary)
        └── Web dashboard      (port 8081)
                │
                ▼
        [ Browser: Knowledge Graph explorer ]
```

---

## Raspberry Pi deployment

The Docker image is built for both `linux/amd64` and `linux/arm64` and is the primary deployment target for Raspberry Pi 4/5 running a 64-bit OS.

**What makes the Pi build work:**

- `HNSWLIB_NO_NATIVE=1` disables CPU-specific optimisations that cause crashes during ARM cross-compilation
- `--prefer-binary` on pip installs avoids source compilation where possible
- Build deps (`rustc`, `cargo`, `cmake`) are included to compile native extensions (ChromaDB, hnswlib) when no binary wheel exists for `linux/arm64`
- The image is intentionally kept single-process (one Python process, two uvicorn servers on separate ports) to minimise memory footprint on constrained hardware

**Typical docker-compose entry (as used in the MeshMonitor stack):**

```yaml
services:
  mempalace:
    image: ghcr.io/ln4cy/mempalace-server:latest
    container_name: mempalace-server
    restart: unless-stopped
    ports:
      - "8000:8000"   # MCP-SSE API
      - "8081:8081"   # Visualization dashboard
    volumes:
      - mempalace-data:/data/mempalace
    environment:
      - PORT_API=8000
      - PORT_DASHBOARD=8081
      - MEMPALACE_PALACE_PATH=/data/mempalace/palace

volumes:
  mempalace-data:   # persists across container recreations
```

The `mempalace-data` named volume keeps the palace (ChromaDB + knowledge graph) intact across image updates and container restarts.

---

## MCP integration

Point any MCP-SSE client at:

```
http://<host>:8000/sse
```

The server implements the full MCP SSE transport (`GET /sse` for the event stream, `POST /messages` for client messages). Tools exposed:

| Tool | Description |
|------|-------------|
| `mempalace_status` | Palace overview and AAAK spec |
| `mempalace_list_wings` | Wings with document counts |
| `mempalace_search` | Semantic search across the palace |
| `mempalace_kg_query` | Query the knowledge graph for an entity |
| `mempalace_kg_add` | Add facts to the knowledge graph |
| `add_observations` | Alias for `mempalace_kg_add` (compatibility) |

---

## Visualization dashboard

The dashboard (port 8081) is a browser-based Knowledge Graph explorer built on [Cytoscape.js](https://cytoscape.js.org/). It visualises the entities and relationships stored by AI agents in real time.

- **Nodes** represent entities (people, topics, locations, concepts) extracted from conversations
- **Edges** represent predicates (relationships between entities)
- Data is served from `/api/graph` on the viz server and refreshes on page load

The dashboard is read-only — agents write via MCP tools; humans explore via the browser.

---

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT_API` | `8000` | MCP-SSE API port |
| `PORT_DASHBOARD` | `8080` | Visualization dashboard port |
| `MEMPALACE_PALACE_PATH` | `/app/data/.mempalace` | Path to palace storage directory |

---

## Development

```bash
pip install -r requirements.txt -r requirements-dev.txt
python server.py

# Tests
pytest tests/

# Lint
ruff check .
```

The `mempalace/` directory is a git submodule pinned to a specific release of the upstream [MemPalace](https://github.com/MemPalace/mempalace) package. To update it:

```bash
git -C mempalace checkout v3.x.x
git add mempalace
git commit -m "chore(submodule): bump mempalace to v3.x.x"
```
