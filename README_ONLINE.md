# SiteForge AI v4 — Hosted API test edition

Deploy to your existing Render Web Service (do not create a second service).

## Render settings
Build: `pip install -r requirements.txt`
Start: `gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --timeout 240`

Environment variables (Render → your existing service → Environment):
- `OPENROUTER_API_KEY`: hosted AI provider secret key (do NOT upload to GitHub)
- `OPENROUTER_MODEL`: a valid model slug listed on https://openrouter.ai/models (choose one that supports code generation and sufficient output)
- `SITEFORGE_TEST_PASSWORD`: a long unique password for private testing. Enter it in the site UI when you generate.

DO NOT share testing code. Do NOT offer public usage yet. There are no customer accounts, payments or per-user quotas. This prototype uses local SQLite and local generated files which can disappear upon Render restarts/deploys. Provider requests can cost money. Set spending limits at the AI provider. This is a private technical test only, NOT ready for paid subscriptions.

If no hosted API key/model is configured, the interface loads, but generation online shows a clear error. Local Ollama fallback still works on your PC if you do not set remote credentials.
