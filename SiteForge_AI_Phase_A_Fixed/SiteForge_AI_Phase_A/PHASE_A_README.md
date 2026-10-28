# SiteForge AI — Phase A fixes

## GitHub deploy
Upload/replace `app.py`, `static/app.js`, `static/index.html` and add `render.yaml` (optional). Keep `static/style.css`, `requirements.txt`, other existing files unchanged. Do not upload secrets. Upload the *contents* of this folder, not its containing directory.

## Render
Existing service → Settings → Start Command: `gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --timeout 210`

Existing service → Environment:
- `OPENROUTER_API_KEY`: secret (never paste publicly)
- `OPENROUTER_MODEL`: valid hosted model slug
- `OPENROUTER_FALLBACK_MODEL`: optional **second distinct** hosted model, used only for recoverable failures
- `OPENROUTER_TIMEOUT`: optional (default 80 seconds, max 95 seconds)
- `SITEFORGE_TEST_PASSWORD`: required for testing on Render

Keep Render private testing password. Paid plans are previews only and no customer accounts exist. OpenRouter requests may incur costs. No billing is enabled.

## Tests
Use a small site prompt and private code. Check Network tab: `/api/generate` should return JSON for both success and failure. If the model responds with empty content/length or provider rate limits, a clear message is shown. Avoid repeated retries on a free quota.

## Limitations
The app still has a **global, not per-user** shared SQLite quota. Render's ephemeral storage can erase projects and SQLite data on restarts. Do not launch publicly as a paid SaaS. Generated HTML and CSS receive limited cleaning; generated JavaScript remains untrusted and must be reviewed before publishing or running outside the sandboxed preview. No third-party scripts should be allowed in generated websites.

## Important architecture
Synchronous requests can still time out on extreme provider delays. Phase B/C should move generation to a persistent job queue with request IDs, polling and durable storage (e.g. Postgres + object storage) prior to real customer usage.
