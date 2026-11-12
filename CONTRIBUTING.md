# Contributing to Neutron

Thank you for your interest in contributing to **Neutron**, the real-time decentralized search engine & web crawler!

---

## Architecture Overview

Neutron consists of three Python ConnectRPC/FastAPI microservices deployed on Render Free + GitHub Pages + Turso LibSQL:

- `services/gateway/` — Public Edge Gateway (REST + SSE `/search/stream` + ConnectRPC `GatewayService`, TTL caching, `slowapi` rate limiting).
- `services/search/` — Index Query & Grounded Synthesis microservice (Turso FTS5, re-ranking, optional Gemini synthesis with extractive fallback).
- `services/crawler/` — On-demand Seed Discovery, `StreamCrawl`, `curl_cffi` fetcher, and `selectolax` HTML-to-Markdown indexer.
- `spaces/crawler/` — Shared crawler/search core modules (`db_turso`, `discovery`, `parser`, `synthesis`, `robots`, `bloom`, `dedup`).
- `proto/neutron/v1/` & `neutron_rpc/` — Protobuf contracts and generated ConnectRPC stubs (`scripts/gen_proto.py`).
- `frontend/` — React 18 + TypeScript + Vite + Tailwind v4 SPA deployed to GitHub Pages.
- `migrations/` — SQLite/LibSQL FTS5 (`03_turso_fts5_schema.sql`) database schema.
- `scripts/` — Turso migration, stale document refresh (`refresh_stale.py`), Protobuf stub generation, and diagnostics.
- `tests/` — Automated unit and live ConnectRPC/SSE integration test suites.

---

## Local Development Setup

### 1. Prerequisites
- Python **3.11** or **3.12**
- Git
- (Optional) Docker & Docker Compose
- A free [Turso](https://turso.tech) database (for live search testing)

### 2. Clone & Install Dependencies
```bash
git clone https://github.com/fahiiim/Neutron-Web-Crawler.git
cd Neutron-Web-Crawler

python -m venv .venv
# Linux/macOS:
source .venv/bin/activate
# Windows PowerShell:
.\.venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

### 3. Configure Environment
```bash
cp .env.example .env
# Generate a secure internal API key:
python -c "import secrets; print(secrets.token_urlsafe(32))"
```
Fill in `INTERNAL_API_KEY`, `TURSO_DATABASE_URL`, and `TURSO_AUTH_TOKEN` inside `.env`.

### 4. Run Database Migrations & Tests
```bash
python scripts/init_turso.py
python -m unittest discover -s tests -v
```

### 5. Run the Microservices + Frontend Locally
```bash
# Terminal 1 - Search Service
PORT=8081 uvicorn services.search.app:app --host 127.0.0.1 --port 8081 --reload

# Terminal 2 - Crawler Service
PORT=8082 uvicorn services.crawler.app:app --host 127.0.0.1 --port 8082 --reload

# Terminal 3 - Edge Gateway
SEARCH_SERVICE_URL=http://127.0.0.1:8081 CRAWLER_SERVICE_URL=http://127.0.0.1:8082 PORT=8080 uvicorn services.gateway.app:app --host 127.0.0.1 --port 8080 --reload

# Terminal 4 - Frontend Dev Server
cd frontend && npm install && VITE_API_BASE_URL=http://127.0.0.1:8080 npm run dev
```
Open `http://localhost:5173` in your browser.

---

## Code Standards

- **Type Annotations:** All new functions and methods must include Python type hints (`typing`).
- **Docstrings:** Document modules, classes, and public functions with clear concise docstrings.
- **Security:**
  - Never commit API keys, tokens, or default hardcoded secrets.
  - Sanitize all HTML/DOM outputs (`textContent`, `DOMPurify`, escaping) to prevent XSS.
  - Parameterize all SQL queries and sanitize FTS5 user expressions.
- **Logging:** Use `structlog` structured logging (`logger.info(...)`, `logger.warning(..., exc_info=True)`). Avoid bare `except Exception: pass`.
- **Tests:** Every bug fix or new feature must include unit tests in `tests/`.

---

## Pull Request Checklist

1. Branch from `main` with a descriptive branch name (`feat/...`, `fix/...`, `docs/...`).
2. Run `python -m unittest discover -s tests -v` and verify all tests pass.
3. Verify code formatting and no lint/type issues.
4. Keep PRs focused and reference any related issues or sections in `CHANGES.md`.
5. Wait for GitHub Actions CI checks (`test`) to pass before merging.
