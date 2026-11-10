# Contributing to Neutron

Thank you for your interest in contributing to **Neutron**, the real-time decentralized search engine & web crawler!

---

## Architecture Overview

Neutron consists of microservices designed to run on free-tier infrastructure (Hugging Face Spaces + Turso LibSQL):

- `spaces/crawler/` — Unified Search Gateway, SSE streaming coordinator, live JIT crawler, background Mercator politeness worker, and web UI (`templates/index.html`).
- `spaces/renderer/` — Isolated Playwright headless Chromium worker for JavaScript-heavy Single Page Applications (SPAs).
- `spaces/gateway/` — Optional standalone gateway microservice for multi-node Docker Compose topologies.
- `migrations/` — SQLite/LibSQL FTS5 and PostgreSQL database schemas.
- `scripts/` — CLI search client, DB inspection, environment checker, and Turso migration scripts.
- `tests/` — Automated unit and integration test suites.

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

### 5. Run the Unified Search & Crawler Service Locally
```bash
cd spaces/crawler
uvicorn app:app --host 0.0.0.0 --port 7860 --reload
```
Open `http://localhost:7860` in your browser.

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
