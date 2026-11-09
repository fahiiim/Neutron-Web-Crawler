---
title: Neutron Stealth Renderer
emoji: 🎭
colorFrom: purple
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# Neutron Stealth Renderer (Hugging Face Space)

Isolated headless Chromium browser microservice for dynamic SPAs and client-rendered pages:
- **Engine**: Playwright Chromium with memory-clamped flags.
- **Asset Interceptor**: Aborts fonts, stylesheets, images, and trackers via `route.abort()` to maintain minimal RAM usage.
- **Port**: `7860`
- **RAM**: 16 GB (Free HF Space - Zero OOM crashes)
