# Deploying Neutron on Render (Free Tier) + GitHub Pages

Neutron runs on **Render Free Web Services** (no credit card required) using **ConnectRPC/gRPC over HTTPS** (`RPC_PROTOCOL=connect`) with your frontend hosted on **GitHub Pages**.

> **Render Free Tier Notes**
> - **750 free instance-hours/month** shared across all free services in your Render workspace.
> - Services **spin down after 15 minutes** of inactivity and take **~30–50 seconds** to wake up on the next request (`RPC_TIMEOUT_MS=55000` is preconfigured so the Gateway waits through cold starts cleanly).
> - Render Free Web Services cannot accept incoming private network traffic, so `SEARCH_SERVICE_URL` and `CRAWLER_SERVICE_URL` must use each service's public `https://*.onrender.com` URL.

---

## Option A: 1-Click Blueprint Deploy (`render.yaml`)

1. Sign in to [dashboard.render.com](https://dashboard.render.com/) with GitHub.
2. Click **New + → Blueprint** and select `fahiiim/Neutron-Web-Crawler` (`render.yaml` is automatically detected).
3. Enter your **Turso** credentials when prompted (`TURSO_DATABASE_URL` and `TURSO_AUTH_TOKEN` for both `neutron-search` and `neutron-crawler`; `INTERNAL_API_KEY` is auto-generated and shared automatically).
4. Once `neutron-search` and `neutron-crawler` finish their first deploy, copy their `https://*.onrender.com` URLs into **`neutron-gateway` → Environment**:
   - `SEARCH_SERVICE_URL` = `https://<your-search-service>.onrender.com`
   - `CRAWLER_SERVICE_URL` = `https://<your-crawler-service>.onrender.com`
5. Wait for `neutron-gateway` to finish redeploying and open `https://<your-gateway-service>.onrender.com/health` (`{"status": "ok"}`).

---

## Option B: Manual 3-Service Setup

Create **3 Web Services** on Render connected to `fahiiim/Neutron-Web-Crawler` (`Free` instance type, **Root Directory** empty):

1. **`neutron-search`**
   - Build Command: `pip install -r services/search/requirements.txt`
   - Start Command: `uvicorn services.search.app:app --host 0.0.0.0 --port $PORT`
   - Health Check Path: `/health`
   - Env Vars: `PYTHON_VERSION=3.12.8`, `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN`, `INTERNAL_API_KEY`, `REQUIRE_INTERNAL_API_KEY=true`

2. **`neutron-crawler`**
   - Build Command: `pip install -r services/crawler/requirements.txt`
   - Start Command: `uvicorn services.crawler.app:app --host 0.0.0.0 --port $PORT`
   - Health Check Path: `/health`
   - Env Vars: `PYTHON_VERSION=3.12.8`, `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN`, `INTERNAL_API_KEY`, `REQUIRE_INTERNAL_API_KEY=true`, `BACKGROUND_CRAWLER_ENABLED=false`

3. **`neutron-gateway`**
   - Build Command: `pip install -r services/gateway/requirements.txt`
   - Start Command: `uvicorn services.gateway.app:app --host 0.0.0.0 --port $PORT`
   - Health Check Path: `/health`
   - Env Vars: `PYTHON_VERSION=3.12.8`, `SEARCH_SERVICE_URL=https://...onrender.com`, `CRAWLER_SERVICE_URL=https://...onrender.com`, `RPC_PROTOCOL=connect`, `RPC_TIMEOUT_MS=55000`, `INTERNAL_API_KEY`, `CORS_ALLOW_ORIGINS=https://fahiiim.github.io`

---

## Connect GitHub Pages to Your Render Gateway

1. In GitHub repo **Settings → Pages → Build and deployment → Source**, choose **GitHub Actions**.
2. In GitHub repo **Settings → Secrets and variables → Actions → Variables**, add:
   - `NEUTRON_API_URL` = `https://<your-gateway-service>.onrender.com`
3. Re-run **Deploy Frontend to GitHub Pages** under **Actions**. Your live site will be served at `https://fahiiim.github.io/Neutron-Web-Crawler/`.

