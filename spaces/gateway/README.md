---
title: Neutron Search Gateway
emoji: 🔍
colorFrom: indigo
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
---

# Neutron Search Gateway (Hugging Face Space)

The public query coordinator and interactive search UI for the Neutron Web Search Engine.

- **Port**: `7860`
- **RAM**: 16 GB (Free HF Space)
- **Role**:
  - Serves the search frontend at `GET /`.
  - Executes sub-15ms BM25 ranking queries against Turso LibSQL FTS5.
  - Cascades sparse/miss queries to `neutron-crawler` via Server-Sent Events (SSE).
  - Fetches and decompresses full markdown articles on demand from Cloudflare R2.
