---
title: Neutron Crawler Worker
emoji: 🕷️
colorFrom: green
colorTo: emerald
sdk: docker
app_port: 7860
pinned: false
---

# Neutron Crawler Worker (Hugging Face Space)

Dual-mode async web crawler and parser:
- **Priority Lane**: Live on-demand JIT crawl requests (<600ms) triggered by `neutron-gateway`.
- **Background Lane**: Continuous politeness frontier crawl (~27,400 pages/day).
- **Extraction**: Zero-Browser Next.js/Nuxt SSR JSON extraction + Selectolax HTML parser.
- **Port**: `7860`
- **RAM**: 16 GB (Free HF Space)
