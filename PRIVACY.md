# Neutron Privacy Policy

**Effective Date:** November 2026  
**Project:** Neutron Web Search Engine & Crawler  

Neutron is engineered from the ground up as a **zero-telemetry, privacy-first search engine**. We believe searching the open web should never create a profile about who you are, what you read, or what you think.

---

## 1. What We Do NOT Collect

- **No IP Address Logging:** Search requests (`/search`, `/search/stream`, `/doc/{url_hash}`) are processed without persisting client IP addresses to any database or analytics store. Rate-limiting counters exist strictly in volatile memory for short sliding windows (60 seconds) and are never written to disk.
- **No Cookies or Tracking Pixels:** Neutron sets **zero tracking cookies**, **zero advertising identifiers**, and **zero third-party analytics scripts** (no Google Analytics, no Mixpanel, no telemetry beacons).
- **No User Accounts or Profiling:** There are no user accounts, login walls, or behavioral search profiles.
- **No Cross-Site Tracking:** Outbound search result links open directly (`rel="noopener noreferrer"`) with no click-tracking redirect wrappers.

---

## 2. What Is Stored

### 2.1 Server-Side (Turso LibSQL Database)
- **Public Web Index (`search_index`, `page_payloads`):** Stores publicly accessible crawled web pages, metadata, compressed article text, and frontier URLs.
- **Aggregated Search Topics (`hot_topics`):** When a query is executed, the normalized query string and an anonymous search frequency counter are stored to improve crawl freshness and power public trending chips. **No user identifier, IP address, timestamp per user, or session ID is associated with `hot_topics`.**

### 2.2 Client-Side (Your Browser Only)
- **Recent Search History (`localStorage`):** Recent searches are saved locally in your browser's `localStorage` (`neutron_search_history`) solely for your convenience. This data **never leaves your browser** and can be cleared anytime from the UI or browser settings.
- **Theme Preference (`localStorage`):** Your dark/light mode preference is stored locally in `localStorage`.

---

## 3. Data Flow Architecture

1. You enter a query in the Neutron UI.
2. Your browser opens an encrypted HTTPS connection directly to the Neutron Search Gateway.
3. Neutron queries the Turso LibSQL FTS5 index (<15ms).
4. If indexed matches are sparse (<5 results), Neutron performs a live Just-In-Time (JIT) crawl across public discovery sources (`DuckDuckGo HTML`, `Wikipedia API`, `HackerNews Algolia`, `Reddit`, `arXiv`, `GitHub`) using server-side requests — **your browser IP is never exposed to third-party discovery providers or crawled sites**.
5. Crawled pages obey `robots.txt` directives and `rel="nofollow"` hints.

---

## 4. External Resources in the Frontend

- **Favicons:** Result cards optionally display site favicons fetched cleanly by the browser from `https://www.google.com/s2/favicons` (can be disabled via privacy preferences or browser blockers without affecting functionality).
- **Fonts & Rendering Libraries:** Google Fonts, Tailwind CSS, `marked.js`, `DOMPurify`, and `highlight.js` may be loaded from public CDNs to format results and render markdown safely in your browser.

---

## 5. Contact & Transparency

Neutron is 100% open source. You can inspect every line of server and client code—and self-host your own private instance—in the [GitHub Repository](https://github.com/fahiiim/Neutron-Web-Crawler).
