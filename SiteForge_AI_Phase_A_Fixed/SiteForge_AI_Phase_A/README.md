# SiteForge AI — Local MVP

An original prototype of an AI website builder, with an English dashboard, local generation using Ollama, isolated HTML preview, and downloadable ZIP source.

## Windows quick start

1. Install Python 3.10+ and Ollama.
2. In a terminal, run `ollama pull qwen3:8b` (if not already installed).
3. Start Ollama and double-click `START_WINDOWS.bat`.
4. Open http://127.0.0.1:5000
5. Enter a brief, select a style, and click **Generate website**.

Alternatively run `python -m pip install -r requirements.txt` and `python app.py`.

## Notes

- No cloud AI API and no payments are required. Ollama runs on your computer.
- If using another model, set environment variable `OLLAMA_MODEL`.
- Generations are stored in `generated/` locally.
- The AI can occasionally return invalid JSON or HTML; retry if needed.
- The generated content must be checked before commercial publishing.
- Preview JavaScript runs inside a restricted sandbox iframe.
- MVP only: no accounts, hosting, billing, or production security hardening. Don't expose this Flask server to the public internet.
- The dashboard font uses Google Fonts and falls back to system fonts offline; the AI-generated sites are instructed not to use external dependencies.


## Pricing preview (v2)
Pricing section: Free ($0, 1 successful generation per rolling 30 days on this local installation), Starter ($15, 20 generations), Pro ($30, 20 generations). Paid plans are **not enabled** and cannot be purchased. The Free limit is stored in `siteforge.db` and does NOT implement per-user identity or production-grade quota enforcement. These are illustrative prices, not promises of features or processed subscriptions.

To launch commercial subscriptions safely, first implement user accounts, server-side entitlements, secure checkout with an authorized payment provider, webhook signature verification, invoices/refunds, usage-based costs, and real multi-user quota enforcement. An eligible adult must handle payment account setup in compliance with the provider terms. Do not expose this Flask development server to the public internet.


### v3 pricing update
- Free: $0, 1 generation / 30 days.
- Starter: $15/month, 20 generations / 30 days (planned).
- Pro: $30/month, unlimited generations (planned, subject to fair-use and hosting capacity).
- Billing and customer-account-based limits are NOT implemented. The active local plan remains Free until a secure payment and user system is implemented.
