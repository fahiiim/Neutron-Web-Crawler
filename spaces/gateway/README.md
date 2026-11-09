---
title: Neutron Search Gateway
emoji: 🔍
colorFrom: indigo
colorTo: blue
sdk: gradio
sdk_version: 4.36.1
app_file: app.py
pinned: false
---

# Neutron Search Gateway (Hugging Face Space)

The public query coordinator and interactive search UI for the Neutron Web Search Engine.

- **SDK**: `gradio` (100% Free Tier, 16 GB RAM, 2 vCPUs)
- **Port**: `7860`
- **Role**:
  - Serves the search frontend at `GET /`.
  - Executes sub-15ms BM25 ranking queries against Turso LibSQL FTS5.
  - Cascades sparse/miss queries to `neutron-crawler` via Server-Sent Events (SSE).
  - Fetches and decompresses full markdown articles on demand from Cloudflare R2.
