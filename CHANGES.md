# Neutron Web Crawler — Complete Changes & Redesign Plan

> **Version**: 3.0 (Codename: Pulsar)  
> **Author**: Neutron Engineering  
> **Date**: November 2026  
> **Status**: Approved — Ready for Implementation

---

## Table of Contents

1. [New Visual Identity: The Spinning Neutron Star](#1-new-visual-identity-the-spinning-neutron-star)
2. [Full UI/UX Redesign](#2-full-uiux-redesign)
3. [Security Fixes](#3-security-fixes)
4. [Crawler Engine Upgrades](#4-crawler-engine-upgrades)
5. [Database & Performance Fixes](#5-database--performance-fixes)
6. [Search Quality Improvements](#6-search-quality-improvements)
7. [New Features](#7-new-features)
8. [Frontend Component Breakdown](#8-frontend-component-breakdown)
9. [File-by-File Change List](#9-file-by-file-change-list)

---

## 1. New Visual Identity: The Spinning Neutron Star

### What We're Removing
The current `index.html` (lines 240–541) renders a **2D spiral galaxy** made of 2,800 point particles in a flat canvas. While visually impressive, it:
- Looks like a generic space animation (many sites have similar particle effects)
- Is 2D with fake 3D perspective projection — no real volumetric depth
- Doesn't communicate "Neutron" — it looks like a galaxy, not a neutron star
- The particles are static dots with no physical behavior

### What We're Building: A Living Neutron Star

The new background will be a **physically-inspired 3D neutron star** rendered on a fullscreen `<canvas>`. It will be the centerpiece of the brand — not just decoration, but the visual identity of Neutron itself.

#### 1.1 The Core Sphere (The Star Itself)

```
Visual: A dense, bright, glowing sphere at the center of the screen.
Size: ~120px diameter (scales with viewport).
Color: Brilliant white core → electric cyan edge → deep blue corona.
Behavior:
  - Visibly SPINNING on its axis (tilted ~23° like a real pulsar).
  - The spin is continuous and smooth at ~0.8 revolutions/second.
  - Surface has faint "hotspot bands" — brighter horizontal stripes
    that rotate with the star, giving the visual impression of a
    solid object spinning (not just a glow blob).
  - A subtle pulsing throb (radius oscillates ±3px at 1.4 Hz)
    synchronized with the "lighthouse beam" sweep.
Rendering: Radial gradient with 5+ color stops, composited with
  globalCompositeOperation = 'lighter' for additive bloom.
```

#### 1.2 The Magnetic Field Lines

```
Visual: Curved lines emanating from the magnetic poles of the star,
  arcing outward and reconnecting at the opposite pole — the classic
  dipole magnetic field topology.
Count: 12 field lines (6 per hemisphere), evenly spaced in longitude.
Color: Semi-transparent cyan (#00f0ff at 15-25% opacity).
Behavior:
  - The field lines ROTATE with the star's spin axis.
  - Because the magnetic axis is TILTED ~40° relative to the spin
    axis (like a real pulsar), the field lines wobble and precess
    as the star spins, creating a mesmerizing 3D tumbling effect.
  - Field lines are drawn as quadratic Bezier curves from pole to
    pole, with control points offset by the tilt angle.
Rendering: ctx.strokeStyle with lineWidth 1.0-1.5, slight blur.
```

#### 1.3 The Lighthouse Beams (Pulsar Jets)

```
Visual: Two narrow, intense conical beams of light shooting out
  from the magnetic poles — the signature feature of a pulsar.
  These are the "searchlights" that sweep across the viewport
  as the star spins.
Color: Core white → cyan → transparent. Gradient along beam length.
Length: Beams extend to ~2x the viewport diagonal (they shoot off-screen).
Width: ~15° cone angle, narrowing to a point at the pole.
Behavior:
  - Because the magnetic axis is tilted relative to the spin axis,
    the beams SWEEP across the screen in a circle as the star rotates.
  - When a beam sweeps past the "camera" (toward the viewer), it
    creates a brief intense FLASH — the classic pulsar pulse.
  - The flash illuminates the entire page briefly (screen-wide glow
    overlay at 8-12% opacity, lasting ~100ms, once per rotation).
  - This creates a rhythmic "heartbeat" visual effect.
Rendering: ctx.createLinearGradient along beam axis, drawn as
  filled triangles with feathered edges.
```

#### 1.4 The Accretion Disk

```
Visual: A thin, flat ring of orbiting matter around the star's equator.
  This is the "disk" of material falling into the neutron star.
Shape: An ellipse (circle viewed at the tilt angle), rendered with
  depth — particles in front of the star vs behind it.
Particle Count: ~600 particles in the disk.
Color: Cyan-to-blue gradient, with brighter inner edge (hotter matter)
  fading to dimmer outer edge.
Behavior:
  - Particles orbit the star with Keplerian speed (inner = faster,
    outer = slower), creating visible differential rotation.
  - The disk is tilted at the spin axis angle, so it appears as an
    ellipse that rocks gently as the user moves their mouse.
  - Particles behind the star are rendered BEFORE the star (depth
    sorting), particles in front rendered AFTER — giving true 3D
    occlusion.
  - Occasional bright "clumps" pass through the disk, simulating
    matter accretion events — these flash brighter momentarily.
Rendering: Individual point particles with size based on depth.
```

#### 1.5 Movement & Drift

```
The entire neutron star system (core + field lines + beams + disk)
DRIFTS slowly across the background:

- Default: Slow circular orbit around the center of the viewport.
  Orbital radius: ~80px. Orbital period: ~45 seconds.
  This creates a gentle, living, breathing feeling — the star is
  never perfectly static.

- Mouse interaction: The star is attracted toward the mouse cursor
  with a soft spring force (like a magnet). Moving the mouse pulls
  the star gently toward it. Releasing lets it drift back to its
  orbit. This creates a playful, interactive feel.

- Search interaction: When the user submits a search query, the
  star briefly ACCELERATES its spin (1.5x speed for 2 seconds),
  the lighthouse beams flare brighter, and a shockwave ring
  expands outward from the star — visual feedback that says
  "the engine is working."

- Scroll parallax: As the user scrolls down (if results extend
  the page), the star drifts upward slightly slower than the
  scroll — parallax depth effect.
```

#### 1.6 Performance Budget

```
Target: 60 FPS on mid-range laptops, 30 FPS on mobile.
Canvas resolution: Capped at 2x device pixel ratio.
Particle count: ~600 disk + 12 field lines + 2 beams + 1 core = light.
  (Down from current 2,800 + 220 + 90 = 3,110 particles.)
GPU: Zero WebGL — pure Canvas 2D API for maximum compatibility.
Battery: requestAnimationFrame with visibility API pause —
  animation stops when the tab is not visible.
Mobile: Reduced particle count (300 disk), no field lines,
  simplified beams. Detected via window.innerWidth < 768.
```

---

## 2. Full UI/UX Redesign

### 2.1 Design Philosophy

```
Current: "Impressive tech demo" — visuals dominate, function follows form.
New:     "Tool you want to use daily" — function leads, visuals support.

Principle 1: SPEED OF USE
  The user should go from opening the page to reading a result in
  under 3 seconds. Every UI element either accelerates this or
  gets removed.

Principle 2: TRANSPARENCY
  Show the user what the crawler is doing. No black boxes. Every
  result shows HOW it was found and WHEN it was crawled.

Principle 3: PROGRESSIVE DISCLOSURE
  Simple by default, powerful on demand. New users see a clean
  search box. Power users discover filters, API access, and
  crawl controls.
```

### 2.2 Layout Changes

#### Header Bar (Simplified)

```
CURRENT (lines 104-133):
  [Pulsar Icon] Neutron [Astra Core badge]     Turso: Online | JIT: Ready | ZeroGPU: Armed

REDESIGNED:
  [Neutron Star Icon] Neutron                   [🟢 Live]  [Stats]  [API Docs]  [GitHub ⭐]

Changes:
  - Remove "Astra Core" badge (means nothing to users).
  - Remove individual service status indicators (users don't care
    about "ZeroGPU: Armed" — they care if search works).
  - Replace with single green "Live" indicator.
  - Add "Stats" link → opens crawl statistics panel.
  - Add "API Docs" link → opens /docs (FastAPI Swagger).
  - Add GitHub star button → social proof and growth.
  - The neutron star icon is a tiny animated version of the
    background star (spins in the header).
```

#### Search Box (Enhanced)

```
CURRENT (lines 148-193):
  [🔍 icon] [___search input___] [Search →]
  Trending: [chip] [chip] [chip] [chip]

REDESIGNED:
  [🔍] [___search input___ (/)] [⌘K] [Search →]
  
  Suggested: [chip] [chip] [chip]     powered by hot_topics
  Recent:    [chip] [chip]            from localStorage

Changes:
  - Add keyboard shortcut hint: "/" to focus (already works, now visible).
  - Add "⌘K" / "Ctrl+K" as alternative shortcut (like Spotlight/VS Code).
  - Trending chips are now DYNAMIC — pulled from the hot_topics table
    via a new GET /trending endpoint, showing what other users search.
  - Add "Recent searches" row from localStorage — personal history.
  - Search input gets AUTOCOMPLETE suggestions as you type (debounced
    300ms, queries hot_topics + search_index titles).
  - The search box has a subtle "breathing" glow that syncs with
    the neutron star's pulse — connecting the UI to the background.
```

#### Live Crawl Progress Panel (NEW)

```
This is the "Transparent Search" feature — the #1 differentiator.

When a search triggers JIT crawling (results < 5), a collapsible
panel slides down below the search box showing real-time crawl activity:

┌─────────────────────────────────────────────────────────────┐
│  ⚡ Live Crawl Progress                              [Hide] │
│                                                             │
│  Phase 1: Index Lookup                                      │
│  ├─ ✅ Turso FTS5 query ..................... 3 hits (11ms) │
│  └─ ℹ️  Less than 5 results — triggering live crawl        │
│                                                             │
│  Phase 2: Source Discovery                                  │
│  ├─ ✅ DuckDuckGo HTML ................... 6 URLs (340ms)   │
│  ├─ ✅ Wikipedia API ..................... 3 URLs (280ms)   │
│  └─ ✅ HackerNews Algolia ............... 2 URLs (190ms)   │
│                                                             │
│  Phase 3: Live Crawling (8 sources)                         │
│  ├─ ✅ en.wikipedia.org ......... indexed (420ms)           │
│  ├─ ✅ stackoverflow.com ........ indexed (380ms)           │
│  ├─ 🔄 medium.com .............. rendering SPA...           │
│  ├─ ✅ github.com ............... indexed (290ms)           │
│  ├─ ⛔ nytimes.com .............. blocked (robots.txt)      │
│  ├─ ✅ arxiv.org ................ indexed (510ms)           │
│  ├─ ❌ reddit.com ............... timeout (4.5s)            │
│  └─ 🔄 dev.to .................. fetching...                │
│                                                             │
│  Total: 6 pages indexed • 1 blocked • 1 failed • 780ms     │
└─────────────────────────────────────────────────────────────┘

Implementation:
  - New SSE events: "discovery_start", "discovery_result",
    "crawl_start", "crawl_success", "crawl_blocked", "crawl_error".
  - Each event carries: source name, URL, duration, status.
  - Frontend renders these into the progress panel in real time.
  - Panel auto-collapses 2 seconds after the last event.
  - User can click [Hide] to dismiss permanently for that search.
```

#### Search Result Cards (Redesigned)

```
CURRENT (lines 667-710):
  ┌────────────────────────────────────────────────┐
  │ [LIVE JIT / FTS5 INDEX] domain.com   Score: 1.0│
  │ Title of the Article                            │
  │ Snippet text preview...                         │
  │ ─────────────────────────────────────────────── │
  │ [📖 Read Full Document]    [Copy Link] [Open →] │
  └────────────────────────────────────────────────┘

REDESIGNED:
  ┌────────────────────────────────────────────────┐
  │ 🌐 domain.com                     ⏱️ Crawled 2m ago │
  │                                                │
  │ Title of the Article                            │
  │ Snippet text preview with the query terms       │
  │ shown in **bold highlighting**...               │
  │                                                │
  │ ─────────────────────────────────────────────── │
  │ [📖 Read]  [📋 Copy]  [↗ Open]   Source: LIVE ⚡│
  └────────────────────────────────────────────────┘

Changes:
  - QUERY TERM HIGHLIGHTING: Bold/highlight the search terms
    within the snippet text. This is the single biggest UX
    improvement for search — users can instantly see WHY this
    result matched their query. (Google does this.)

  - FRESHNESS INDICATOR: Show "Crawled 2m ago" / "Crawled 3 days
    ago" / "Crawled just now" — tells the user how fresh the data is.
    Uses the crawled_at field from search_index.

  - FAVICON: Fetch favicon from Google's favicon service:
    https://www.google.com/s2/favicons?domain=example.com&sz=32
    Shows the site's actual icon next to the domain.

  - SOURCE BADGE: Moved to bottom-right, smaller. "INDEX" (from
    FTS5 cache) or "LIVE ⚡" (just crawled in real-time).

  - REMOVE SCORE DISPLAY: Users don't care about "Score: 1.0".
    Keep it in the API response but hide from the UI.

  - SMOOTH ENTRY ANIMATION: Cards slide up + fade in with a
    staggered 80ms delay between each. Creates a cascading
    "waterfall" reveal effect.

  - SKELETON LOADING: While results load, show 3 skeleton cards
    (grey pulsing rectangles) — standard modern UX pattern.
```

#### Document Reader Modal (Enhanced)

```
CURRENT (lines 209-228):
  A plain text modal with raw markdown dumped as plaintext.

REDESIGNED:
  - RENDER MARKDOWN: Parse the full_markdown content and render
    it as actual formatted HTML (headings, bold, links, code
    blocks, lists, tables). Use a lightweight markdown renderer
    like marked.js or markdown-it (loaded from CDN).

  - SYNTAX HIGHLIGHTING: Code blocks inside the document get
    syntax highlighting via highlight.js or Prism.js.

  - TABLE OF CONTENTS: Auto-generate a sidebar TOC from the
    document's headings (h1-h4). Clicking a heading scrolls
    to that section.

  - READING PROGRESS: A thin cyan progress bar at the top of
    the modal showing how far the user has scrolled.

  - COPY BUTTON: "Copy as Markdown" button to copy the raw
    source for pasting into notes/docs.

  - SHARE LINK: Generate a shareable link: /doc/{url_hash}
    that opens the reader directly (deep linking).

  - KEYBOARD NAVIGATION: Arrow keys to move between documents
    in the search results without closing the modal.

  - CLOSE ON OUTSIDE CLICK: Click outside the modal to close
    (currently only the X button and Escape key work).
```

#### Footer (Redesigned)

```
CURRENT (line 231-233):
  "Neutron Real-Time Engine • Hugging Face Spaces • Turso LibSQL • Astra 3D Particle Vortex Core"

REDESIGNED:
  ┌──────────────────────────────────────────────────────────┐
  │  🔒 Zero Tracking • Zero Cookies • Zero Telemetry       │
  │  Open Source • Powered by Turso & Hugging Face           │
  │  [GitHub] [API Docs] [Privacy] [Status]                  │
  └──────────────────────────────────────────────────────────┘

  - Lead with privacy promise (the #1 user trust signal).
  - Remove "Astra 3D Particle Vortex Core" (internal jargon).
  - Add useful links.
```

### 2.3 Mobile Responsiveness

```
CURRENT: Basic responsive via Tailwind (sm: breakpoints).
ISSUE: The 3D particle canvas and glass cards don't adapt well
  to small screens. The search input is hard to tap.

CHANGES:
  - Search box: Full-width with larger tap target (min 48px height).
  - Result cards: Single-column, no horizontal padding waste.
  - Trending chips: Horizontally scrollable row (not wrapped).
  - Document modal: Full-screen on mobile (not centered floating).
  - Neutron star: Simplified (fewer particles, no field lines).
  - Header: Hamburger menu for links on small screens.
  - Touch: Swipe left/right on result cards to navigate documents.
```

### 2.4 Accessibility

```
CURRENT: Zero accessibility features.

CHANGES:
  - All interactive elements get proper aria-labels.
  - Search results are a <ul role="list"> with <li role="listitem">.
  - Modal has role="dialog" with aria-modal="true".
  - Focus trap inside modal when open.
  - Skip-to-content link for screen readers.
  - Color contrast: All text meets WCAG AA (4.5:1 ratio).
    Current white-on-black is fine; cyan-on-black (#00f0ff on #000)
    has 10.3:1 contrast — excellent.
  - Reduced motion: @media (prefers-reduced-motion: reduce) stops
    the neutron star animation and disables card transitions.
  - Keyboard navigation: Tab through results, Enter to open,
    Escape to close modal.
```

### 2.5 Dark/Light Mode

```
CURRENT: Dark mode only (pure black background).

CHANGES:
  - Keep dark mode as default (matches the neutron star aesthetic).
  - Add light mode toggle in header for users who prefer it.
  - Light mode: White background, dark text, neutron star rendered
    with reduced opacity (15%) as a subtle watermark.
  - Preference saved to localStorage and respects
    @media (prefers-color-scheme).
```

---

## 3. Security Fixes

### 3.1 Remove Hardcoded API Key

```
File: spaces/crawler/config.py (Line 18)
File: spaces/gateway/config.py

CURRENT:
  INTERNAL_API_KEY: str = "neutron-secret-internal-key"

CHANGE:
  INTERNAL_API_KEY: str  # No default — REQUIRES env var

  Add validation in config:
    @validator('INTERNAL_API_KEY')
    def key_must_be_set(cls, v):
        if not v or v == "neutron-secret-internal-key":
            raise ValueError(
                "INTERNAL_API_KEY must be set to a secure random value. "
                "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(32))\""
            )
        return v

  Also update .env.example with:
    INTERNAL_API_KEY=CHANGE_ME_TO_A_RANDOM_SECRET
```

### 3.2 Fix XSS Vulnerability

```
File: spaces/crawler/templates/index.html (Line 694)

CURRENT:
  onclick="readDocument('${item.url_hash}', '${escapeHtml(item.title || item.url)}')"
  
  The escapeHtml function only handles &, <, >, ", ' — but the entire
  card innerHTML is built via template literals, and item.url is NOT
  escaped in the href attributes.

CHANGE:
  - Build result cards using DOM API instead of innerHTML:
    const titleEl = document.createElement('h2');
    titleEl.textContent = item.title;  // textContent auto-escapes
    
  - OR: Use a sanitization library (DOMPurify) to clean all
    dynamic content before innerHTML insertion.

  - Escape ALL dynamic values in onclick handlers, href, and
    text content — not just the title.
```

### 3.3 Add Rate Limiting

```
File: spaces/crawler/app.py

CHANGE: Add rate limiting middleware using slowapi or custom semaphore.

  from slowapi import Limiter
  from slowapi.util import get_remote_address

  limiter = Limiter(key_func=get_remote_address)

  @app.get("/search")
  @limiter.limit("30/minute")
  async def search_endpoint(...):
      ...

  @app.get("/search/stream")
  @limiter.limit("15/minute")
  async def search_stream(...):
      ...

  Also enforce MAX_CONCURRENT_JIT_FETCHES using asyncio.Semaphore:
  
  _jit_semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_JIT_FETCHES)

  async def fetch_and_index_document(...):
      async with _jit_semaphore:
          ...  # existing fetch logic
```

### 3.4 Sanitize FTS5 Query Input

```
File: spaces/crawler/db_turso.py (Line 100-114)

CURRENT: Raw tokens are quoted but special FTS5 operators (OR, NOT,
  NEAR, AND) embedded in user input could alter query semantics.

CHANGE:
  - Strip all FTS5 special characters: *, ^, OR, NOT, AND, NEAR, +, -
  - Whitelist only alphanumeric tokens:
    
    import re
    raw_tokens = re.findall(r'[a-zA-Z0-9]+', query.lower())
```

---

## 4. Crawler Engine Upgrades

### 4.1 Implement SimHash Near-Duplicate Detection

```
File: spaces/crawler/app.py (around Line 338)

CURRENT: SimHash is computed and stored, but never compared.

CHANGE: Before inserting a new document, check if any existing
  document in the same domain has a SimHash within Hamming distance ≤ 3.

  async def is_near_duplicate(simhash_val: int, domain_hash: int) -> bool:
      """Check if a near-duplicate exists in the index."""
      sql = """
      SELECT simhash FROM search_index
      WHERE domain_hash = ?
      LIMIT 200;
      """
      rows = await turso_crawler_client._client.execute(sql, [domain_hash])
      for row in rows.rows:
          existing = int(row["simhash"])
          hamming = bin(simhash_val ^ existing).count('1')
          if hamming <= 3:
              return True
      return False

  In fetch_and_index_document(), add before insert:
      if await is_near_duplicate(simhash_val, domain_id):
          return None  # Skip near-duplicate
```

### 4.2 Add URL Bloom Filter

```
File: NEW — spaces/crawler/bloom.py

PURPOSE: O(1) memory check before fetching any URL. Avoids
  re-crawling known URLs without hitting the database.

  import mmh3
  from bitarray import bitarray

  class URLBloomFilter:
      def __init__(self, capacity=1_000_000, fp_rate=0.001):
          self.size = int(-capacity * math.log(fp_rate) / (math.log(2) ** 2))
          self.hash_count = int((self.size / capacity) * math.log(2))
          self.bits = bitarray(self.size)
          self.bits.setall(0)

      def add(self, url: str) -> None:
          for seed in range(self.hash_count):
              idx = mmh3.hash(url, seed) % self.size
              self.bits[idx] = 1

      def might_contain(self, url: str) -> bool:
          return all(
              self.bits[mmh3.hash(url, seed) % self.size]
              for seed in range(self.hash_count)
          )

  Usage in fetch_and_index_document():
      if url_bloom.might_contain(url):
          return None  # Already crawled (probably)
      # ... fetch and index ...
      url_bloom.add(url)
```

### 4.3 Add Retry with Exponential Backoff

```
File: spaces/crawler/app.py (around Line 301)

CURRENT: Single fetch attempt. Failure = URL abandoned forever.

CHANGE:
  MAX_RETRIES = 3
  RETRY_BACKOFF = [0.5, 1.5, 3.0]  # seconds

  async def fetch_with_retry(session, url, max_retries=3):
      for attempt in range(max_retries):
          try:
              response = await session.get(url, timeout=4.5 + attempt)
              if response.status_code == 200:
                  return response
              if response.status_code in (429, 503):
                  # Rate limited or overloaded — back off
                  await asyncio.sleep(RETRY_BACKOFF[attempt])
                  continue
              return response  # 4xx errors — don't retry
          except Exception:
              if attempt < max_retries - 1:
                  await asyncio.sleep(RETRY_BACKOFF[attempt])
      return None
```

### 4.4 Add Sitemap.xml Parser

```
File: NEW — spaces/crawler/sitemap.py

PURPOSE: Parse sitemap.xml and sitemap index files to discover
  thousands of URLs from a single HTTP request.

  import xml.etree.ElementTree as ET

  async def discover_sitemap_urls(
      client: httpx.AsyncClient, domain: str, max_urls: int = 100
  ) -> List[str]:
      urls = []
      sitemap_url = f"https://{domain}/sitemap.xml"
      try:
          resp = await client.get(sitemap_url, timeout=5.0)
          if resp.status_code != 200:
              return urls
          root = ET.fromstring(resp.text)
          ns = {'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
          
          # Check if it's a sitemap index
          for sitemap in root.findall('.//sm:sitemap/sm:loc', ns):
              # Recursively parse child sitemaps
              ...
          
          # Parse URL entries
          for url_elem in root.findall('.//sm:url/sm:loc', ns):
              urls.append(url_elem.text.strip())
              if len(urls) >= max_urls:
                  break
      except Exception:
          pass
      return urls

  Integration: Call from discover_seed_urls() as a 4th parallel
  discovery source, using the domains already found.
```

### 4.5 Add Structured Logging

```
File: ALL Python files

CURRENT: print() statements with [Prefix] tags. 11 instances of
  "except Exception: pass" that silently swallow errors.

CHANGE: Replace all print() and silent except with structlog:

  import structlog
  logger = structlog.get_logger()

  # Instead of:
  print(f"[Fetch Error for {url}]: {exc}")

  # Use:
  logger.error("fetch_failed", url=url, error=str(exc), exc_info=True)

  # Instead of:
  except Exception:
      pass

  # Use:
  except Exception:
      logger.warning("frontier_enqueue_failed", url=item["url"], exc_info=True)

  Benefits:
    - JSON-structured logs for parsing and monitoring.
    - Stack traces preserved (exc_info=True).
    - Log levels (debug/info/warning/error) for filtering.
    - Correlation IDs for tracing requests across microservices.
```

### 4.6 Enforce Concurrency Limits

```
File: spaces/crawler/app.py

CURRENT: MAX_CONCURRENT_JIT_FETCHES=12 is configured but NEVER used.
  All JIT fetches run in unlimited parallel.

CHANGE:
  _jit_semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_JIT_FETCHES)

  async def fetch_and_index_document(session, url, ...):
      async with _jit_semaphore:
          # ... existing logic ...

  This caps concurrent outbound connections to 12, preventing
  the crawler from overwhelming target servers or exhausting
  local file descriptors.
```

---

## 5. Database & Performance Fixes

### 5.1 Atomic Frontier Lease

```
File: spaces/crawler/db_turso.py (Lines 242-273)

CURRENT: SELECT then UPDATE — race condition where two workers
  can lease the same URL.

CHANGE: Use a single atomic statement:

  async def lease_next_frontier_url(self):
      sql = """
      UPDATE frontier_queue
      SET status = 1, lease_expires_at = DATETIME('now', '+5 minutes')
      WHERE url_hash = (
          SELECT url_hash FROM frontier_queue
          WHERE status = 0
          ORDER BY priority_score DESC, discovered_at ASC
          LIMIT 1
      )
      RETURNING url_hash, domain_hash, url;
      """
      rs = await self._client.execute(sql)
      if rs.rows:
          row = rs.rows[0]
          return {
              "url_hash": int(row["url_hash"]),
              "domain_hash": int(row["domain_hash"]),
              "url": str(row["url"]),
          }
      return None

  Also add a lease expiration recovery job that resets stale leases:
  
  async def recover_expired_leases(self):
      sql = """
      UPDATE frontier_queue SET status = 0
      WHERE status = 1 AND lease_expires_at < DATETIME('now');
      """
      await self._client.execute(sql)
```

### 5.2 Batch Frontier Inserts

```
File: spaces/crawler/db_turso.py (Lines 215-240)

CURRENT: 20 individual INSERT statements = 20 round-trips to Turso.

CHANGE: Use Turso's batch API to execute all inserts in one request:

  async def enqueue_frontier_urls(self, urls):
      if not urls:
          return 0
      statements = []
      for item in urls:
          statements.append(libsql_client.Statement(
              "INSERT OR IGNORE INTO frontier_queue "
              "(url_hash, domain_hash, url, priority_score, status) "
              "VALUES (?, ?, ?, ?, 0)",
              [item["url_hash"], item["domain_hash"],
               item["url"], item.get("priority", 0.5)]
          ))
      result = await self._client.batch(statements)
      return len(result)
```

### 5.3 Transactional Index + Payload Insert

```
File: spaces/crawler/db_turso.py (Lines 161-213)

CURRENT: Index metadata and payload BLOB are inserted in two
  separate non-transactional statements. If payload INSERT fails,
  index exists without content.

CHANGE: Wrap both in a Turso batch (implicit transaction):

  async def insert_search_index(self, ...):
      statements = [
          libsql_client.Statement(sql_index, [...]),
      ]
      if compressed_text:
          statements.append(
              libsql_client.Statement(sql_payload, [url_hash, compressed_text])
          )
      await self._client.batch(statements)
```

---

## 6. Search Quality Improvements

### 6.1 Query Term Highlighting in Snippets

```
File: spaces/crawler/templates/index.html (JS)

CHANGE: Before rendering snippet text, wrap matching query terms
  in <mark> tags:

  function highlightTerms(text, query) {
      const terms = query.toLowerCase().split(/\s+/).filter(t => t.length > 2);
      let result = escapeHtml(text);
      for (const term of terms) {
          const regex = new RegExp(`(${escapeRegex(term)})`, 'gi');
          result = result.replace(regex,
            '<mark class="bg-cyan-400/30 text-white rounded px-0.5">$1</mark>'
          );
      }
      return result;
  }
```

### 6.2 Broader Content Extraction

```
File: spaces/crawler/parser.py (Line 111)

CURRENT: Only extracts h1, h2, h3, p elements.

CHANGE:
  CONTENT_SELECTORS = (
      "article", "main", "[role='main']",
      "h1", "h2", "h3", "h4",
      "p", "li", "td", "th",
      "blockquote", "pre", "code",
      "figcaption", "summary", "details",
      ".post-content", ".article-body", ".entry-content",
  )

  for node in tree.css(", ".join(CONTENT_SELECTORS)):
      text = node.text(strip=True)
      if text and len(text) > 15:
          text_blocks.append(text)
```

### 6.3 Add More Discovery Sources

```
File: spaces/crawler/discovery.py

CURRENT: 3 sources (DuckDuckGo, Wikipedia, HackerNews).

ADD:
  - Brave Search API (free tier: 2000 queries/month)
  - Reddit search via old.reddit.com/search.json
  - arXiv API for academic papers
  - GitHub code search for programming queries
  - Common Crawl index for historical pages

  Each as an async adapter function following the existing pattern.
  All run in parallel with the existing 3 sources.
```

### 6.4 Respect rel="nofollow"

```
File: spaces/crawler/parser.py (Lines 43-55)

CURRENT: All <a[href]> links are extracted regardless of rel attribute.

CHANGE:
  for anchor in tree.css("a[href]"):
      rel = anchor.attributes.get("rel", "").lower()
      if "nofollow" in rel or "noopener" in rel:
          continue  # Skip nofollow links from frontier queue
      ...
```

---

## 7. New Features

### 7.1 GET /trending Endpoint

```
Purpose: Power the dynamic trending chips in the UI.

  @app.get("/trending")
  async def get_trending():
      sql = """
      SELECT term, frequency FROM hot_topics
      ORDER BY frequency DESC, last_searched_at DESC
      LIMIT 8;
      """
      rows = await turso_crawler_client._client.execute(sql)
      return {
          "trending": [
              {"term": r["term"], "count": r["frequency"]}
              for r in rows.rows
          ]
      }
```

### 7.2 GET /stats Endpoint

```
Purpose: Power the crawl stats dashboard.

  @app.get("/stats")
  async def get_stats():
      index_count = await turso_crawler_client._client.execute(
          "SELECT COUNT(*) as cnt FROM search_index"
      )
      frontier_count = await turso_crawler_client._client.execute(
          "SELECT COUNT(*) as cnt FROM frontier_queue WHERE status = 0"
      )
      domain_count = await turso_crawler_client._client.execute(
          "SELECT COUNT(DISTINCT domain_hash) as cnt FROM search_index"
      )
      return {
          "pages_indexed": index_count.rows[0]["cnt"],
          "frontier_pending": frontier_count.rows[0]["cnt"],
          "domains_covered": domain_count.rows[0]["cnt"],
          "background_crawler_active": _bg_worker_task is not None
                                       and not _bg_worker_task.done(),
      }
```

### 7.3 Crawl Progress SSE Events

```
Purpose: Power the Live Crawl Progress Panel in the UI.

CHANGE in search_stream() — emit granular events:

  # Discovery phase
  yield {"event": "discovery_start", "data": json.dumps(
      {"sources": ["duckduckgo", "wikipedia", "hackernews"]}
  )}

  # For each discovery source:
  yield {"event": "discovery_result", "data": json.dumps(
      {"source": "duckduckgo", "url_count": 6, "duration_ms": 340}
  )}

  # Crawl phase — for each URL:
  yield {"event": "crawl_start", "data": json.dumps(
      {"url": url, "domain": domain}
  )}
  yield {"event": "crawl_success", "data": json.dumps(
      {"url": url, "domain": domain, "title": title, "duration_ms": 420}
  )}
  # or:
  yield {"event": "crawl_blocked", "data": json.dumps(
      {"url": url, "domain": domain, "reason": "robots.txt"}
  )}
  yield {"event": "crawl_error", "data": json.dumps(
      {"url": url, "domain": domain, "error": "timeout"}
  )}
```

### 7.4 Search History (Client-Side)

```
File: spaces/crawler/templates/index.html (JS)

  const HISTORY_KEY = 'neutron_search_history';
  const MAX_HISTORY = 20;

  function saveSearch(query) {
      let history = JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]');
      history = history.filter(q => q !== query);
      history.unshift(query);
      history = history.slice(0, MAX_HISTORY);
      localStorage.setItem(HISTORY_KEY, JSON.stringify(history));
  }

  function getRecentSearches(limit = 5) {
      const history = JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]');
      return history.slice(0, limit);
  }

  // Render as chips below trending:
  const recent = getRecentSearches();
  if (recent.length > 0) {
      // Render "Recent: [chip] [chip] [chip]"
  }
```

---

## 8. Frontend Component Breakdown

### Complete UI Component Tree (New Design)

```
<body>
├── <canvas id="neutron-star-canvas">        ← NEW: spinning neutron star
│   ├── Core sphere (spinning, pulsing)
│   ├── Magnetic dipole field lines (precessing)
│   ├── Lighthouse beams (sweeping)
│   ├── Accretion disk particles (orbiting)
│   └── Mouse interaction + search pulse
│
├── <div class="app-container">
│   ├── <header>
│   │   ├── Logo + "Neutron" text
│   │   ├── [🟢 Live] status indicator
│   │   ├── [Stats] → opens stats panel
│   │   ├── [API] → opens /docs
│   │   ├── [GitHub ⭐] → repo link
│   │   └── [🌙/☀️] theme toggle
│   │
│   ├── <main>
│   │   ├── Hero title + subtitle
│   │   │
│   │   ├── Search form
│   │   │   ├── Search icon
│   │   │   ├── Input field (autofocus, autocomplete)
│   │   │   ├── Keyboard hint ("/" or "⌘K")
│   │   │   └── Submit button
│   │   │
│   │   ├── Chip rows
│   │   │   ├── Trending: [dynamic chips from /trending]
│   │   │   └── Recent: [chips from localStorage]
│   │   │
│   │   ├── Live Crawl Progress Panel (collapsible)  ← NEW
│   │   │   ├── Phase 1: Index lookup status
│   │   │   ├── Phase 2: Discovery source results
│   │   │   └── Phase 3: Per-URL crawl status
│   │   │
│   │   ├── Skeleton loaders (3 cards, shown while loading)  ← NEW
│   │   │
│   │   ├── Results container
│   │   │   └── Result cards (with highlighting, favicons,
│   │   │       freshness, smooth entry animation)
│   │   │
│   │   └── "No results" empty state
│   │
│   ├── Document Reader Modal (enhanced)
│   │   ├── Header: title + source badge + close button
│   │   ├── TOC sidebar (auto-generated)              ← NEW
│   │   ├── Rendered markdown content                  ← NEW
│   │   ├── Reading progress bar                       ← NEW
│   │   └── Footer: [Copy Markdown] [Share Link] [Close]
│   │
│   ├── Stats Panel (slide-in overlay)                 ← NEW
│   │   ├── Pages indexed counter
│   │   ├── Domains covered counter
│   │   ├── Frontier queue depth
│   │   ├── Background crawler status
│   │   └── Index freshness chart
│   │
│   └── <footer>
│       ├── Privacy badges
│       └── Links: GitHub, API Docs, Privacy, Status
```

---

## 9. File-by-File Change List

### Modified Files

| File | Type of Change | Summary |
|------|---------------|---------|
| `spaces/crawler/app.py` | Major | Add rate limiting, concurrency semaphore, SimHash dedup check, Bloom filter, retry logic, granular SSE events, `/trending` endpoint, `/stats` endpoint, structured logging |
| `spaces/crawler/config.py` | Security | Remove default API key, add validation, add new config fields for retry/bloom/rate-limit |
| `spaces/crawler/db_turso.py` | Major | Atomic frontier lease (UPDATE RETURNING), batch inserts, transactional index+payload, FTS5 input sanitization, add trending query method |
| `spaces/crawler/dedup.py` | Minor | Add `www.` stripping, percent-encoding normalization, more tracking params (msclkid, twclid, etc.) |
| `spaces/crawler/discovery.py` | Medium | Add Brave Search, Reddit, arXiv adapters. Rotate user agents. |
| `spaces/crawler/parser.py` | Medium | Broader content selectors (article, li, blockquote, etc.), nofollow checking, structured data extraction |
| `spaces/crawler/robots.py` | Minor | Per-domain locking instead of global lock, user agent consistency |
| `spaces/crawler/compression.py` | None | No changes needed |
| `spaces/crawler/storage_r2.py` | Minor | Remove dead code or integrate properly |
| `spaces/crawler/templates/index.html` | **Complete Rewrite** | New neutron star animation, redesigned UI components, query highlighting, live crawl progress, skeleton loading, markdown rendering, accessibility, mobile optimization |
| `spaces/gateway/app.py` | Medium | Same security fixes, rate limiting, trending/stats endpoints |
| `spaces/gateway/main.py` | Cleanup | Remove (duplicate of app.py) or consolidate |
| `spaces/renderer/app.py` | Medium | Concurrency limiter, smart wait (networkidle), content extraction |
| `spaces/renderer/main.py` | Cleanup | Consolidate with app.py |
| `tests/test_core.py` | Major | Add 30+ tests for parser, robots, discovery, search, frontier, SSE |
| `requirements.txt` | Minor | Add slowapi, structlog, mmh3, bitarray, markdown-it-py |
| `README.md` | Major | Add demo GIF, architecture Mermaid, benchmarks, contributor guide |
| `.github/workflows/ci_cd.yml` | Minor | Add linting step, security scanning |
| `docker-compose.yml` | Minor | Add resource limits, health checks |

### New Files

| File | Purpose |
|------|---------|
| `spaces/crawler/bloom.py` | URL Bloom filter for O(1) dedup |
| `spaces/crawler/sitemap.py` | Sitemap.xml parser for URL discovery |
| `spaces/crawler/middleware.py` | Rate limiting and security middleware |
| `CHANGES.md` | This document |
| `PRIVACY.md` | Public privacy policy |
| `CONTRIBUTING.md` | Contributor guidelines |

---

> **Total estimated changes**: ~3,500 lines modified, ~1,200 lines added, ~400 lines removed.  
> **Timeline**: 3–4 focused development weeks.  
> **Priority order**: Security (Week 1) → Engine (Week 2) → UI/UX + Neutron Star (Week 3) → Testing & Polish (Week 4).
