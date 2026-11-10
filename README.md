# Neutron v3.0 (Pulsar): Real-Time Decentralized Web Search Engine

A cloud-native, **zero-telemetry** microservice search engine and live web crawler powered by **FastAPI**, **Turso (LibSQL FTS5)**, and **Playwright Chromium**, designed to run on **free-tier Hugging Face Spaces (\$0/month)** with a **Spinning 3D Neutron Star Pulsar** UI and **Transparent Live Search**.

---

## Key Highlights (v3.0 Pulsar)

- **Spinning 3D Neutron Star UI**: Custom Canvas 2D physical pulsar visualization featuring rotating plasma hotspot bands, precessing dipole magnetic field lines, sweeping lighthouse beams with periodic flash, depth-occluded Keplerian accretion disk, orbital drift, mouse magnetic attraction, and search shockwaves.
- **Transparent Search (Live Crawl Progress)**: Real-time Server-Sent Events (SSE) stream showing every phase—Turso FTS5 lookup, multi-source discovery (`DuckDuckGo`, `Wikipedia`, `HackerNews`, `arXiv`, `GitHub`, `Reddit`, optional `Brave`), per-domain crawl latency, and `robots.txt` blocks.
- **Hardened Crawler Core**:
  - **O(1) URL Bloom Filter** (`mmh3` + `bitarray`) warmed from Turso at startup.
  - **SimHash Near-Duplicate Detection** (weighted unigrams + 2-gram shingles, Hamming distance <= 3).
  - **Bounded Concurrency & Retries**: `asyncio.Semaphore` clamping + exponential backoff (`429`/`502`/`503`/`504`).
  - **Atomic Frontier Queue**: SQLite `UPDATE ... RETURNING` lease lock + automatic 5-minute lease expiration recovery.
  - **Sitemap.xml & Robots.txt Politeness**: Per-domain async locking, recursive sitemap index + `.xml.gz` support, `rel="nofollow"` filtering.
  - **Rich Content Extraction**: JSON-LD, OpenGraph, `__NEXT_DATA__` SSR, and semantic HTML-to-Markdown conversion.
- **Security & Privacy First**:
  - Zero cookies, zero IP persistence, zero click-tracking redirects ([PRIVACY.md](PRIVACY.md)).
  - Constant-time internal bearer verification (`hmac.compare_digest`), rate limiting (`slowapi`), FTS5 query sanitization, and `DOMPurify`-hardened Markdown document reader.

---

## Architecture Topology

```mermaid
flowchart LR
    User["User Browser / API"] -->|"HTTPS + SSE"| Crawler["Space 1: Neutron_Crawler\n(FastAPI + Gradio + UI)"]
    Crawler -->|"FTS5 BM25 <15ms\nBatch Transactions"| Turso[("Turso LibSQL\nFTS5 + Zstd Payloads")]
    Crawler -->|"6 Parallel Discovery\nAdapters + Sitemaps"| Web["Open Web\n(curl_cffi Chrome TLS)"]
    Crawler -->|"SPA Escalation\nHTTPS + Bearer"| Renderer["Space 2: Neutron_Renderer\n(Playwright Chromium)"]
    Renderer --> Web
```

---

## Performance & Design Comparison

| Capability | Neutron v3.0 | Traditional Search |
| :--- | :--- | :--- |
| **Indexed Query Latency** | `< 15ms` (Turso LibSQL FTS5) | `~50–150ms` |
| **Live Freshness** | Real-time SSE JIT crawl on sparse hits | Delayed batch re-index |
| **Crawl Transparency** | Full per-source & per-domain live trace | Opaque black box |
| **Telemetry / Tracking** | Zero cookies, zero IP storage | Extensive user profiling |
| **Infrastructure Cost** | `$0/month` (HF Spaces + Turso free tier) | Enterprise clusters |

---

## Quick Start

### 1. Database Initialization (Turso LibSQL)
```bash
cp .env.example .env
# Generate a secure internal secret:
python -c "import secrets; print(secrets.token_urlsafe(32))"
# Configure TURSO_DATABASE_URL, TURSO_AUTH_TOKEN, and INTERNAL_API_KEY in .env

python scripts/init_turso.py
```

### 2. Run Tests
```bash
pip install -r requirements.txt
python -m unittest discover -s tests -v
```

### 3. Run Locally
```bash
# Option A: Direct Unified Service
cd spaces/crawler
uvicorn app:app --host 0.0.0.0 --port 7860 --reload

# Option B: Full Multi-Service Docker Compose
docker compose up --build
```
Open **`http://localhost:7860`** in your browser.

---

## Hugging Face Spaces CI/CD Deployment

GitHub Actions (`.github/workflows/ci_cd.yml`) automatically runs on every push to `main`:
1. **`test`**: Syntax verification + `unittest` suite.
2. **`database-migration`**: Executes `scripts/init_turso.py` against Turso using `TURSO_DATABASE_URL` and `TURSO_AUTH_TOKEN`.
3. **`deploy-huggingface`**: Syncs `spaces/renderer` (`Neutron_Renderer`) and `spaces/crawler` (`Neutron_Crawler`) to Hugging Face Spaces via `HfApi` using `HF_TOKEN` and `HF_USERNAME`.

Configure these variables/secrets inside each Hugging Face Space's **Settings -> Variables and secrets**:
- `INTERNAL_API_KEY` (shared random secret between Crawler & Renderer)
- `TURSO_DATABASE_URL` & `TURSO_AUTH_TOKEN` (on `Neutron_Crawler`)
- `RENDERER_SERVICE_URL` (`https://<username>-neutron-renderer.hf.space` on `Neutron_Crawler`)

---

## Documentation
- [CHANGES.md](CHANGES.md) — Detailed v3.0 engineering & UI/UX design plan
- [PRIVACY.md](PRIVACY.md) — Privacy architecture & zero-telemetry guarantees
- [CONTRIBUTING.md](CONTRIBUTING.md) — Development setup & PR guidelines
