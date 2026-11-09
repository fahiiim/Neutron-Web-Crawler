import asyncio
from typing import Optional
from fastapi import FastAPI, HTTPException, Header, Depends
from pydantic import BaseModel
from playwright.async_api import async_playwright, Browser, BrowserContext

from shared.config import settings

app = FastAPI(
    title="Neutron Stealth Renderer Microservice",
    description="Isolated Playwright Chromium worker for rendering dynamic SPAs and WAF bypass."
)

class RenderRequest(BaseModel):
    url: str

_playwright = None
_browser: Optional[Browser] = None

def verify_internal_auth(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = authorization.split(" ")[1]
    if token != settings.INTERNAL_API_KEY:
        raise HTTPException(status_code=403, detail="Forbidden")

@app.on_event("startup")
async def startup():
    global _playwright, _browser
    try:
        _playwright = await async_playwright().start()
        # Launch Chromium with strict low-memory flags
        _browser = await _playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--renderer-process-limit=1",
                "--js-flags=--max-old-space-size=256"
            ]
        )
        print("[Renderer] Headless Chromium launched successfully.")
    except Exception as e:
        print(f"[Renderer] Warning: Could not launch Chromium: {e}")

@app.on_event("shutdown")
async def shutdown():
    global _browser, _playwright
    if _browser:
        await _browser.close()
    if _playwright:
        await _playwright.stop()

@app.get("/health")
async def health():
    return {"status": "ok", "service": "svc-stealth-renderer", "browser_ready": _browser is not None}

@app.post("/render", dependencies=[Depends(verify_internal_auth)])
async def render_page(req: RenderRequest):
    """Render a dynamic SPA, aborting heavy assets (images/fonts/css) to preserve memory."""
    if not _browser:
        raise HTTPException(status_code=503, detail="Headless browser not initialized")

    context: BrowserContext = await _browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
        viewport={"width": 1280, "height": 720}
    )
    page = await context.new_page()

    # Block images, stylesheets, fonts, and trackers to keep memory minimal
    async def route_interceptor(route):
        if route.request.resource_type in ["image", "media", "font", "stylesheet"]:
            await route.abort()
        else:
            await route.continue_()

    await page.route("**/*", route_interceptor)

    try:
        await page.goto(req.url, wait_until="domcontentloaded", timeout=6000)
        # Brief pause for hydration
        await asyncio.sleep(0.5)

        title = await page.title()
        # Extract body text
        text = await page.inner_text("body")
        text = " ".join(text.split())

        snippet = text[:300] if text else ""

        return {
            "url": req.url,
            "title": title[:200],
            "snippet": snippet,
            "text": text[:5000]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Rendering failed: {str(e)}")
    finally:
        await page.close()
        await context.close()

