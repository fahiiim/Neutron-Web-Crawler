---
title: Neutron Stealth Renderer
emoji: 🎭
colorFrom: purple
colorTo: indigo
sdk: gradio
sdk_version: 4.36.1
app_file: app.py
pinned: false
---

# Neutron Stealth Renderer (Hugging Face Space)

Isolated headless Chromium browser microservice for dynamic SPAs:
- **SDK**: `gradio` (100% Free Tier, 16 GB RAM, 2 vCPUs)
- **Engine**: Playwright Chromium with memory-clamped flags.
- **Asset Interceptor**: Aborts fonts, stylesheets, images, and trackers via `route.abort()`.
- **Port**: `7860`
