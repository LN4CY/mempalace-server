# MemPalace-Viz

A high-performance standalone service and visualization dashboard for the [MemPalace](https://github.com/MemPalace/mempalace) semantic memory system.

This project wraps the core MemPalace logic into a networked service using **MCP-SSE**, allowing any AI agent to call its 19+ tools over the network. It also includes a premium web-based Knowledge Graph explorer.

## Features

- **MCP-SSE Server**: Exposes MemPalace tools (Search, KG, Mining, Diary) via industry-standard Server-Sent Events.
- **Visual Dashboard**: Premium, interactive graph visualization using Cytoscape.js.
- **Raspberry Pi Ready**: Lightweight and highly configurable for resource-constrained environments.
- **Production Hardened**: Built-in health checks and robust network protocols.

## Architecture

```
[ AI Responder ] <--- MCP-SSE (Port 8000) ---> [ MemPalace-Viz ]
                                                     |
                                                     +---> [ Core MemPalace ]
                                                     |
[ Web Browser ] <---- HTTP (Port 8080) -------> [ Dashboard ]
```

## Configuration

Control the service using the following environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `PORT_API` | Port for the MCP-SSE and Dashboard API | `8000` |
| `PORT_DASHBOARD` | Port for the web dashboard interface | `8080` |
| `MEMPALACE_PALACE_PATH`| Path to the persistent storage directory | `~/.mempalace` |

## Deployment (Docker)

To run as part of the Meshtastic AI Responder stack:

```yaml
services:
  mempalace-viz:
    image: mempalace-viz:latest
    ports:
      - "8080:8080"
    volumes:
      - mempalace_data:/app/data/.mempalace
```

## Integration

To connect an MCP client (like AI Responder), use the following server URL:
`http://mempalace-viz:8000/sse`

---
*Created by Antigravity AI for the MemPalace community.*
