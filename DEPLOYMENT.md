# Deployment (cartozo.ai)

**Branching:** See [BRANCHING.md](BRANCHING.md). Deploy from `live` branch.

**Config:** Local dev uses `.env` + `.env.local` (see `.env.local.example`). Production uses env vars in hosting UI.

---

For production, set these **environment variables** in your hosting platform (DigitalOcean Droplet, Railway, Render, etc.):

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | No | SQLite by default (`data/app.db`). For PostgreSQL: `postgresql://user:pass@host:5432/dbname` |
| `GOOGLE_CLIENT_ID` | Yes | From [Google Cloud Console](https://console.cloud.google.com/apis/credentials) |
| `GOOGLE_CLIENT_SECRET` | Yes | From same credentials |
| `DEPLOY_URL` | Yes | `https://cartozo.ai` |
| `SESSION_SECRET` | Yes | Random string, 32+ chars |

**SQLite (default):** No setup needed. Database file is created at `data/app.db` on first run. Ideal for DigitalOcean Droplet (single server).

**PostgreSQL:** Set `DATABASE_URL` if you need multi-worker or managed DB. Tables are created automatically on startup.

**Migration:** To migrate existing `data/users.json` and `data/feedback.json`, run: `python -m scripts.migrate_json_to_db`

**Google Console:** Add `https://cartozo.ai/auth/google/callback` to Authorized redirect URIs and `https://cartozo.ai` to Authorized JavaScript origins.

**Note:** Never commit `.env` or real secrets to the repo. Use your host's environment variables UI.
