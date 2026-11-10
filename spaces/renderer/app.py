"""Stealth Renderer Microservice (FastAPI + Playwright Chromium + Gradio SDK).

Renders JavaScript-heavy Single Page Applications (SPAs) with bounded concurrency,
asset abortion, smart network-idle waiting, and clean main-content extraction.
"""

import asyncio
from contextlib import asynccontextmanager
import hmac
import subprocess
import sys
from typing import Any, AsyncGenerator, Dict, List, Optional

try:
    import spaces

    @spaces.GPU
    def _zero_gpu_guard() -> str:
        """Hugging Face ZeroGPU requirement guard."""
        return "Neutron Stealth Renderer Online"
except Exception:
    def _zero_gpu_guard() -> str:
        return "Neutron Stealth Renderer Online"


def _notify_zerogpu_startup() -> None:
    """Explicitly trigger ZeroGPU startup report if running under ZeroGPU container."""
    try:
        import spaces.zero

        if hasattr(spaces.zero, "startup"):
            spaces.zero.startup()
        else:
            import spaces.zero.client as zero_client

            zero_client.startup_report()
    except Exception:
        pass


_notify_zerogpu_startup()

from fastapi import Depends, FastAPI, Header, HTTPException
from playwright.async_api import Browser, BrowserContext, async_playwright
from pydantic import BaseModel, Field
from selectolax.lexbor import LexborHTMLParser
import structlog

try:
    import gradio as gr
except ImportError:
    gr = None

try:
    from .config import settings
except ImportError:
    from config import settings

logger = structlog.get_logger("neutron.renderer")


class RenderRequest(BaseModel):
    """Payload schema for single URL rendering requests."""

    url: str = Field(..., min_length=8, max_length=2048)


_playwright_instance = None
_shared_browser: Optional[Browser] = None
_render_semaphore = asyncio.Semaphore(max(1, settings.MAX_CONCURRENT_RENDERS))


def verify_internal_auth(
    authorization: Optional[str] = Header(None),
) -> None:
    """Verify bearer token from internal callers using constant-time comparison."""
    expected = settings.INTERNAL_API_KEY
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="Internal authentication is not configured on this server.",
        )
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing authorization header")
    token = authorization.split(" ", 1)[1].strip()
    if not hmac.compare_digest(token.encode("utf-8"), expected.encode("utf-8")):
        raise HTTPException(status_code=403, detail="Invalid internal API key")


def _extract_clean_text(html: str) -> str:
    """Strip chrome/navigation elements and extract clean Markdown-like text blocks."""
    tree = LexborHTMLParser(html)
    for junk in tree.css(
        "script, style, noscript, svg, nav, footer, aside, "
        "[role='navigation'], .cookie-banner, .advertisement, .ads"
    ):
        junk.decompose()

    scope = tree
    for selector in ("article", "main", "[role='main']", ".post-content", ".article-body"):
        candidate = tree.css_first(selector)
        if candidate and len(candidate.text(strip=True)) >= 200:
            scope = candidate
            break

    blocks: List[str] = []
    seen = set()
    for node in scope.css("h1, h2, h3, h4, p, li, blockquote, pre"):
        txt = node.text(strip=True)
        if not txt or len(txt) <= 15 or txt in seen:
            continue
        seen.add(txt)
        tag = (node.tag or "").lower()
        if tag == "h1":
            blocks.append(f"# {txt}")
        elif tag == "h2":
            blocks.append(f"## {txt}")
        elif tag == "h3":
            blocks.append(f"### {txt}")
        elif tag == "li":
            blocks.append(f"- {txt}")
        elif tag == "blockquote":
            blocks.append(f"> {txt}")
        else:
            blocks.append(txt)
    return "\n\n".join(blocks)


def ensure_playwright_installed() -> None:
    """Ensure Chromium browser binary is downloaded in the Hugging Face environment."""
    try:
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            check=True,
            capture_output=True,
        )
    except Exception as exc:
        logger.warning("playwright_install_warning", error=str(exc))


async def init_browser_async() -> None:
    global _playwright_instance, _shared_browser
    try:
        ensure_playwright_installed()
        _playwright_instance = await async_playwright().start()
        _shared_browser = await _playwright_instance.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--renderer-process-limit=1",
                "--js-flags=--max-old-space-size=512",
            ],
        )
        logger.info("renderer_chromium_initialized")
    except Exception as exc:
        logger.error("renderer_browser_launch_failed", error=str(exc), exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Launch headless Chromium asynchronously on startup."""
    _notify_zerogpu_startup()
    if not settings.INTERNAL_API_KEY:
        logger.warning("renderer_internal_api_key_missing")
    init_task = asyncio.create_task(init_browser_async())
    yield
    if not init_task.done():
        init_task.cancel()
    if _shared_browser is not None:
        try:
            await _shared_browser.close()
        except Exception:
            pass
    if _playwright_instance is not None:
        try:
            await _playwright_instance.stop()
        except Exception:
            pass
    logger.info("renderer_shutdown_complete")


app = FastAPI(
    title="Neutron Stealth Renderer",
    description="Isolated Playwright Chromium worker for rendering dynamic SPAs.",
    version="3.0.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health_check() -> Dict[str, Any]:
    """Health check endpoint for Hugging Face Spaces."""
    return {
        "status": "ok",
        "service": "neutron-renderer",
        "version": "3.0.0",
        "browser_ready": _shared_browser is not None,
    }


@app.post("/render", dependencies=[Depends(verify_internal_auth)])
async def render_page_endpoint(request: RenderRequest) -> Dict[str, Any]:
    """Render a dynamic SPA with concurrency clamping and smart hydration waiting."""
    if _shared_browser is None:
        raise HTTPException(status_code=503, detail="Chromium browser not available")

    if not request.url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Only http/https URLs are supported")

    async with _render_semaphore:
        context: BrowserContext = await _shared_browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 720},
        )
        page = await context.new_page()

        async def route_interceptor(route: Any) -> None:
            if route.request.resource_type in ("image", "media", "font", "stylesheet"):
                await route.abort()
            else:
                await route.continue_()

        await page.route("**/*", route_interceptor)

        try:
            await page.goto(
                request.url,
                wait_until="domcontentloaded",
                timeout=settings.RENDER_TIMEOUT_MS,
            )
            try:
                await page.wait_for_load_state("networkidle", timeout=3500)
            except Exception:
                await asyncio.sleep(0.5)

            title = await page.title()
            rendered_html = await page.content()
            clean_text = _extract_clean_text(rendered_html)
            if len(clean_text) < 100:
                raw_text = await page.inner_text("body")
                clean_text = " ".join(raw_text.split())

            snippet = clean_text.lstrip("#>- ").strip()[:300] if clean_text else ""

            return {
                "url": request.url,
                "title": title[:200],
                "snippet": snippet,
                "text": clean_text[:12000],
            }
        except Exception as exc:
            logger.warning("render_failed", url=request.url, error=str(exc))
            raise HTTPException(status_code=500, detail=f"Rendering error: {exc}")
        finally:
            await page.close()
            await context.close()


if gr is not None:
    with gr.Blocks(title="Neutron Stealth Renderer") as demo:
        gr.Markdown("# Neutron Stealth Renderer")
        gr.Markdown("Isolated headless Chromium browser service for dynamic SPAs.")
        gr.Markdown("Status: **Active** | Engine: **Playwright Chromium**")

        with gr.Row():
            status_box = gr.Textbox(value="Initializing...", label="Renderer Status")
            status_btn = gr.Button("Refresh Status")

        status_btn.click(fn=_zero_gpu_guard, inputs=[], outputs=[status_box])
        demo.load(fn=_zero_gpu_guard, inputs=[], outputs=[status_box])

    app = gr.mount_gradio_app(app, demo, path="/")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=settings.PORT)
