---
title: Neutron Crawler Worker
emoji: 🕷️
colorFrom: green
colorTo: blue
sdk: gradio
sdk_version: 4.36.1
app_file: app.py
pinned: false
---

# Neutron Crawler Worker (Hugging Face Space)

Dual-mode async web crawler and parser:
- **SDK**: `gradio` (100% Free Tier, 16 GB RAM, 2 vCPUs)
- **Priority Lane**: Live on-demand JIT crawl requests (<600ms) triggered by `neutron-gateway`.
- **Background Lane**: Continuous politeness frontier crawl (~27,400 pages/day).
- **Extraction**: Zero-Browser Next.js/Nuxt SSR JSON extraction + Selectolax HTML parser.
- **Port**: `7860`
