# SiteForge AI — Phase B (private beta authentication)

## Before deployment
1. Back up the current GitHub repository. Keep payments disabled.
2. Provision a PostgreSQL database (persistent; free Render web filesystem is ephemeral). Set Render `DATABASE_URL` to its **internal** PostgreSQL connection URI if in same region. This can cost money; check price before proceeding.
3. Set `SECRET_KEY` to a securely generated random value (at least 32 bytes), only in Render Environment. Keep `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, `SITEFORGE_TEST_PASSWORD`. Never commit secrets.
4. Replace existing files at repository ROOT, not in an extra folder.
5. `DATABASE_URL` and `SECRET_KEY` must be set before the first boot. Do not proceed if either is missing on Render.
6. **Initial beta schema only:** Start Command: `python init_db.py && gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --timeout 210` (creates tables idempotently). For **future schema changes**, initialize Flask-Migrate/Alembic on a development computer and commit revisions. `create_all()` does not migrate existing tables.

## Test
- `GET /api/auth/me` should return unauthenticated + CSRF.
- Register with email, password 12+ characters, and existing beta code; sign in, sign out and sign in again.
- Confirm anonymous generation gives 401 and authenticated generation works.
- Confirm free generation quota is counted per user, but keep registration private.

## Known limitations / not launch-ready
- Password reset email is **not implemented**. Do not open public registration yet.
- Project files are stored temporarily on Render disk; project-to-user ownership is process-memory only and downloads are not persistent after restart. Phase C must move projects to object storage and DB.
- No email verification, account recovery, distributed rate limits or CSRF middleware hardening beyond JSON POST token checks. Do not market this as production ready.
- The beta code must remain secret. Paid plans are not active and cannot be self-activated.
- Registration and generation requests should be limited with an external edge rate limiter before public exposure.
