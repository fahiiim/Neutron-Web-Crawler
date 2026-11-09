# Neutron: 10M-Page Real-Time Web Search Engine

A cloud-native, microservice search engine powered by **FastAPI**, **Turso (LibSQL FTS5)**, and **Cloudflare R2**, deployed across **3 independent Hugging Face Spaces (48 GB total RAM, $0/month)**.

---

## Architecture Topology

```
                              [ User Web / API Traffic ]
                                          │
                                          ▼
┌───────────────────────────────────────────────────────────────────────────────────┐
│ SPACE 1: neutron-gateway (FastAPI) [Port 7860 • 16 GB RAM • Free HF Space]        │
│ • Serves interactive real-time search UI at GET /                                 │
│ • Sub-15ms BM25 ranking directly against Turso LibSQL FTS5                        │
│ • If results < 5, streams live JIT crawl results via Server-Sent Events (SSE)     │
│ • Fetches compressed full-text markdown articles on demand from Cloudflare R2     │
└───────────────────────┬───────────────────────────────────────────────────────────┘
                        │ HTTPS / Bearer Token
                        ▼
┌───────────────────────────────────────────────────────────────────────────────────┐
│ SPACE 2: neutron-crawler (FastAPI) [Port 7860 • 16 GB RAM • Free HF Space]        │
│ • Priority Lane: On-demand JIT user burst fetches (<600ms via curl_cffi)          │
│ • Background Lane: 27,400 pages/day Mercator politeness frontier loop             │
│ • Zero-Browser Next.js / Nuxt SSR JSON extractor + Selectolax parser              │
│ • Pushes compressed markdown chunks to R2 and writes FTS5 index to Turso          │
└───────────────────────┬───────────────────────────────────────────────────────────┘
                        │ HTTPS (Only if page is an empty client-side SPA)
                        ▼
┌───────────────────────────────────────────────────────────────────────────────────┐
│ SPACE 3: neutron-renderer (Playwright) [Port 7860 • 16 GB RAM • Free HF Space]    │
│ • Memory-clamped headless Chromium worker                                         │
│ • Aborts images, media, CSS, and fonts via route.abort() for ultra-fast rendering │
│ • Runs inside 16 GB RAM with zero fear of OOM (Out Of Memory) crashes             │
└───────────────────────────────────────────────────────────────────────────────────┘
```

---

## 1. Cloud Credential Setup ($0/Month)

### A. Turso LibSQL (Search Index & Frontier)
1. Install Turso CLI or log into [turso.tech](https://turso.tech).
2. Create your database:
   ```bash
   turso db create neutron-search
   ```
3. Retrieve database URL and authentication token:
   ```bash
   turso db show neutron-search --url
   turso db tokens create neutron-search
   ```
4. Apply the FTS5 schema:
   ```bash
   turso db shell neutron-search < migrations/03_turso_fts5_schema.sql
   ```

### B. Cloudflare R2 (Full-Text Object Storage)
1. Log into [dash.cloudflare.com](https://dash.cloudflare.com) $\rightarrow$ **R2**.
2. Click **Create bucket** $\rightarrow$ Name it `neutron-page-cache`.
3. Go to **Manage R2 API Tokens** $\rightarrow$ **Create API Token** (Object Read & Write permission).
4. Save:
   * `R2_ACCOUNT_ID`
   * `R2_ACCESS_KEY_ID`
   * `R2_SECRET_ACCESS_KEY`
   * `R2_ENDPOINT_URL` (`https://<account_id>.r2.cloudflarestorage.com`)

---

## 2. Deploying to 3 Hugging Face Spaces

Hugging Face allows unlimited public Spaces, each with **16 GB RAM and 2 vCPUs** for free.

### Step 1: Create the 3 Spaces on Hugging Face
Go to [huggingface.co/new-space](https://huggingface.co/new-space) and create 3 separate Spaces:

| Space Name | Space SDK | Port | Local Directory |
| :--- | :--- | :--- | :--- |
| `neutron-renderer` | **Docker** | `7860` | `spaces/renderer/` |
| `neutron-crawler` | **Docker** | `7860` | `spaces/crawler/` |
| `neutron-gateway` | **Docker** | `7860` | `spaces/gateway/` |

### Step 2: Push Each Subfolder to its Respective Space
Each folder in `spaces/` is a self-contained Git repository with its own `Dockerfile`, `README.md`, and dependencies:

```bash
# Example: Deploying neutron-renderer
cd spaces/renderer
git init
git remote add origin https://huggingface.co/spaces/<your-username>/neutron-renderer
git add .
git commit -m "deploy renderer"
git push -u origin main --force
```
*(Repeat the same process for `spaces/crawler` and `spaces/gateway`)*

### Step 3: Configure Environment Secrets in Hugging Face
In each Space's **Settings $\rightarrow$ Variables and secrets**, add:

* **For `neutron-renderer`:**
  * `INTERNAL_API_KEY`
* **For `neutron-crawler`:**
  * `INTERNAL_API_KEY`
  * `TURSO_DATABASE_URL`
  * `TURSO_AUTH_TOKEN`
  * `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_ENDPOINT_URL`
  * `RENDERER_SERVICE_URL` (`https://<your-username>-neutron-renderer.hf.space`)
* **For `neutron-gateway`:**
  * `INTERNAL_API_KEY`
  * `TURSO_DATABASE_URL`
  * `TURSO_AUTH_TOKEN`
  * `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_ENDPOINT_URL`
  * `CRAWLER_SERVICE_URL` (`https://<your-username>-neutron-crawler.hf.space`)

---

## 3. Local Development (Docker Compose)

You can run the entire 3-microservice topology locally before pushing to Hugging Face:

```bash
# 1. Fill in credentials
cp .env.example .env

# 2. Launch all 3 services
docker compose up --build
```

Access the interactive search engine at:
👉 **`http://localhost:7860`**
