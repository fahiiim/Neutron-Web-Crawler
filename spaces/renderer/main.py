"""Stealth Renderer Microservice (FastAPI + Playwright Chromium).

Renders JavaScript-heavy Single Page Applications (SPAs) and bypasses client
challenges while aborting heavy media assets to ensure minimal resource overhead.
"""

import asyncio
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Dict, Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from playwright.async_api import Browser, BrowserContext, async_playwright
from pydantic import BaseModel

from config import settings


class RenderRequest(BaseModel):
    """Payload schema for single URL rendering requests."""

    url: str


_playwright_instance = None
_shared_browser: Optional[Browser] = None


def verify_internal_auth(
    authorization: Optional[str] = Header(None),
) -> None:
    """Verify bearer token from internal callers."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing authorization header")
    token = authorization.split(" ")[1]
    if token != settings.INTERNAL_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid internal API key")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Launch persistent headless Chromium on startup and terminate on shutdown."""
    global _playwright_instance, _shared_browser
    try:
        _playwright_instance = await async_playwright().start()
        _shared_browser = await _playwright_instance.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--renderer-process-limit=1",
                "--js-flags=--max-old-space-size=256",
            ],
        )
        print("[Renderer] Headless Chromium initialized successfully.")
    except Exception as exc:
        print(f"[Renderer Browser Launch Warning]: {exc}")

    yield

    if _shared_browser is not None:
        await _shared_browser.close()
    if _playwright_instance is not None:
        await _playwright_instance.stop()
    print("[Renderer] Headless Chromium closed.")


app = FastAPI(
    title="Neutron Stealth Renderer",
    description="Isolated Playwright Chromium worker for rendering dynamic SPAs.",
    version="2.0.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health_check() -> Dict[str, Any]:
    """Health check endpoint for Hugging Face Spaces."""
    return {
        "status": "ok",
        "service": "neutron-renderer",
        "browser_ready": _shared_browser is not None,
    }


@app.post("/render", dependencies=[Depends(verify_internal_auth)])
async def render_page_endpoint(request: RenderRequest) -> Dict[str, Any]:
    """Render a dynamic SPA, aborting media, font, and CSS requests to minimize RAM.

    Args:
        request: Target URL payload.

    Returns:
        Extracted title, snippet, and body text.
    """
    if _shared_browser is None:
        raise HTTPException(status_code=503, detail="Chromium browser not available")

    context: BrowserContext = await _shared_browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1280, "height": 720},
    )
    page = await context.new_page()

    # Resource filter: abort images, videos, fonts, and stylesheets to save memory
    async def route_interceptor(route: Any) -> None:
        if route.request.resource_type in ["image", "media", "font", "stylesheet"]:
            await route.abort()
        else:
            await route.continue_()

    await page.route("**/*", route_interceptor)

    try:
        await page.goto(request.url, wait_until="domcontentloaded", timeout=6500)
        await asyncio.sleep(0.5)  # Brief pause for hydration

        title = await page.title()
        raw_text = await page.inner_text("body")
        clean_text = " ".join(raw_text.split())

        snippet = clean_text[:300] if clean_text else ""

        return {
            "url": request.url,
            "title": title[:200],
            "snippet": snippet,
            "text": clean_text[:5000],
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Rendering error: {exc}")
    finally:
        await page.close()
        await context.close()
