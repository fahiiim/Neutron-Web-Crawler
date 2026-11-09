# Neutron Web Crawler & Real-Time Search Engine

A cloud-native, microservice-based real-time search engine with just-in-time (JIT) crawl discovery, focused background indexing (10M pages/year), and zero-cost cloud infrastructure.

---

## Architecture Overview

```
                                [ External Search Traffic ]
                                             │
                                             ▼
                             ┌───────────────────────────────┐
                             │   Kubernetes Ingress (Nginx)  │
                             └───────────────┬───────────────┘
                                             │
                                             ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ 1. svc-search-gateway (Port 8000)                                                      │
│ • Endpoints: GET /search, GET /search/stream (SSE), GET /doc/{url_hash}, GET /health   │
│ • Direct BM25 ranking against Turso FTS5 (<15ms)                                       │
│ • If results < 5, dispatches live JIT crawl to svc-crawler-worker                      │
└───────────────────────┬────────────────────────────────────────────┬───────────────────┘
                        │ Cluster DNS (Port 8001)                    │
                        ▼                                            ▼ Cluster DNS (Port 8002)
┌───────────────────────────────────────────┐      ┌─────────────────────────────────────┐
│ 2. svc-crawler-worker (Port 8001)         │      │ 3. svc-stealth-renderer (Port 8002) │
│ • Priority Lane: JIT user burst fetches   │ SPA? │ • Single-tab isolated Chromium pool │
│ • curl_cffi with Chrome 124 TLS JA3/JA4   ├─────►│ • Headless Chrome for WAF/Client SPAs│
│ • Zero-Browser Next.js/Nuxt SSR extractor │      │ • Aborts images/css/fonts for memory │
│ • Uploads full text to Cloudflare R2      │      └─────────────────────────────────────┘
│ • Writes index to Turso LibSQL FTS5       │
└───────────────────────┬───────────────────┘
                        │
                        ▼
       ┌─────────────────────────────────┐
       │ CLOUD STORAGE LAYER             │
       │ • Turso LibSQL (9 GB Free FTS5) │
       │ • Cloudflare R2 (10 GB Free S3) │
       └─────────────────────────────────┘
```

---

## 1. Cloud Credential Setup ($0/Month)

### A. Turso LibSQL (Search Index & Frontier)
1. Install Turso CLI or log into [turso.tech](https://turso.tech).
2. Create database:
   ```bash
   turso db create neutron-search
   ```
3. Get connection URL and authentication token:
   ```bash
   turso db show neutron-search --url
   turso db tokens create neutron-search
   ```
4. Initialize the FTS5 schema:
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

## 2. Local Microservices (Docker Compose)

1. Copy `.env.example` to `.env` and fill in credentials:
   ```bash
   cp .env.example .env
   ```
2. Build and launch all 3 microservices:
   ```bash
   docker compose up --build
   ```
3. Test search:
   ```bash
   curl "http://localhost:8000/search?q=zig+async+io"
   ```

---

## 3. Kubernetes Deployment

Apply the manifests to your cluster (Minikube, Kind, K3s, or Oracle Cloud OKE):

```bash
# 1. Create namespace
kubectl apply -f k8s/00-namespace.yaml

# 2. Configure secrets & configmap
# (Update values in k8s/01-secrets.yaml and k8s/02-configmap.yaml first)
kubectl apply -f k8s/01-secrets.yaml
kubectl apply -f k8s/02-configmap.yaml

# 3. Deploy microservices
kubectl apply -f k8s/10-gateway.yaml
kubectl apply -f k8s/20-crawler.yaml
kubectl apply -f k8s/30-renderer.yaml

# 4. Deploy ingress
kubectl apply -f k8s/40-ingress.yaml
```

Check pod status:
```bash
kubectl get pods -n neutron
```

