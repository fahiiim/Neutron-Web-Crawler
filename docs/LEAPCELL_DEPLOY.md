# Deploying Neutron on Leapcell + GitHub Pages

Neutron runs as **three independent ConnectRPC/gRPC Python microservices** on **Leapcell** (serverless free tier, no credit card) paired with the React frontend on **GitHub Pages**.

All inter-service contracts live in [`proto/neutron/v1/neutron.proto`](../proto/neutron/v1/neutron.proto), using `connectrpc` (`ProtocolType.CONNECT` / `ProtocolType.GRPC_WEB` / `ProtocolType.GRPC`) mounted alongside FastAPI/Uvicorn on port `8080`.

---

## 1. Deploy the 3 Leapcell Microservices

Create **3 Web Services** in the [Leapcell Dashboard](https://leapcell.io/) connected to this GitHub repository, leaving **Root Directory** at the repository root (`.`) for all three so each service uses its own lean `requirements.txt` and shares `neutron_rpc/`.

> Generate one strong shared secret first:
> `python -c "import secrets; print(secrets.token_urlsafe(32))"`

### Service A: `neutron-search` (Index Query & Cited Synthesis)
- **Runtime**: `Python`
- **Build Command**: `pip install -r services/search/requirements.txt`
- **Start Command**: `uvicorn services.search.app:app --host 0.0.0.0 --port 8080`
- **Port**: `8080`
- **Environment Variables**:
  - `TURSO_DATABASE_URL` = your Turso DB URL
  - `TURSO_AUTH_TOKEN` = your Turso auth token
  - `INTERNAL_API_KEY` = `<shared-secret>`
  - `REQUIRE_INTERNAL_API_KEY` = `true`

### Service B: `neutron-crawler` (On-Demand Discovery & Extraction)
- **Runtime**: `Python`
- **Build Command**: `pip install -r services/crawler/requirements.txt`
- **Start Command**: `uvicorn services.crawler.app:app --host 0.0.0.0 --port 8080`
- **Port**: `8080`
- **Environment Variables**:
  - `TURSO_DATABASE_URL` = your Turso DB URL
  - `TURSO_AUTH_TOKEN` = your Turso auth token
  - `INTERNAL_API_KEY` = `<shared-secret>`
  - `REQUIRE_INTERNAL_API_KEY` = `true`
  - `BACKGROUND_CRAWLER_ENABLED` = `false` *(keeps Leapcell serverless compliant)*

### Service C: `neutron-gateway` (Public Edge REST + SSE + ConnectRPC)
- **Runtime**: `Python`
- **Build Command**: `pip install -r services/gateway/requirements.txt`
- **Start Command**: `uvicorn services.gateway.app:app --host 0.0.0.0 --port 8080`
- **Port**: `8080`
- **Environment Variables**:
  - `SEARCH_SERVICE_URL` = `https://<your-search-service>.leapcell.dev`
  - `CRAWLER_SERVICE_URL` = `https://<your-crawler-service>.leapcell.dev`
  - `RPC_PROTOCOL` = `connect` *(uses Connect over HTTP/1.1 & HTTP/2, safe behind Leapcell HTTP ingress)*
  - `INTERNAL_API_KEY` = `<shared-secret>`
  - `CORS_ALLOW_ORIGINS` = `https://fahiiim.github.io` *(or `*` during testing)*

---

## 2. Deploy the Frontend to GitHub Pages

1. In your GitHub repo go to **Settings → Pages → Source** and choose **GitHub Actions**.
2. Go to **Settings → Secrets and variables → Actions → Variables** and add:
   - `NEUTRON_API_URL` = `https://<your-gateway-service>.leapcell.dev`
3. Push to `main` (or trigger `.github/workflows/deploy_pages.yml` manually).

Your UI deploys to `https://fahiiim.github.io/Neutron-Web-Crawler/`. You can also override or swap the Gateway URL anytime directly inside the UI under **Index → Backend Gateway URL**.

---

## 3. Regenerating Protobuf / ConnectRPC Stubs (Optional)

```bash
python scripts/gen_proto.py
```

