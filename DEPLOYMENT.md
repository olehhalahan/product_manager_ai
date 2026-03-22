# Deployment (cartozo.ai)

**Branching:** See [BRANCHING.md](BRANCHING.md). Deploy from `live` branch.

**Config:** Local dev uses `.env` + `.env.local` (see `.env.local.example`). Production uses env vars in hosting UI.

---

For production, set these **environment variables** in your hosting platform (DigitalOcean Droplet, Railway, Render, etc.):

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | No | SQLite by default (`data/app.db`). For PostgreSQL: `postgresql://user:pass@host:5432/dbname` |
| `GOOGLE_CLOUD_PROJECT_ID` | Recommended | Same project as OAuth client (Console project ID, e.g. `my-app-123`) |
| `GOOGLE_CLIENT_ID` | Yes | OAuth 2.0 Web Client from [Credentials](https://console.cloud.google.com/apis/credentials) in that project |
| `GOOGLE_CLIENT_SECRET` | Yes | From same OAuth client |
| `DEPLOY_URL` | Yes | `https://cartozo.ai` |
| `SESSION_SECRET` | Yes | Random string, 32+ chars |
| `GTM_CONTAINER_ID` | No | GTM container (e.g. `GTM-XXXXXX`). In GTM: Google Tag / GA4 Config, Trigger: All Pages |

**SQLite (default):** No setup needed. Database file is created at `data/app.db` on first run. Ideal for DigitalOcean Droplet (single server).

**PostgreSQL:** Set `DATABASE_URL` if you need multi-worker or managed DB. Tables are created automatically on startup.

**Migration:** To migrate existing `data/users.json` and `data/feedback.json`, run: `python -m scripts.migrate_json_to_db`

**Google Console:** Add `https://cartozo.ai/auth/google/callback` and `https://cartozo.ai/auth/google/merchant/callback` to Authorized redirect URIs; add `https://cartozo.ai` to Authorized JavaScript origins.

**Merchant Center / Merchant API:** In [Google Cloud Console](https://console.cloud.google.com/apis/library) enable **Merchant API** (not the deprecated Content API for Shopping) in the **same** project as `GOOGLE_CLOUD_PROJECT_ID`. In **OAuth consent screen → Scopes**, add `https://www.googleapis.com/auth/content`. Users connect from `/upload` via **Connect Merchant Center**; the app stores a refresh token per user for future product uploads.

**Developer registration:** Google requires linking that GCP project to each Merchant Center account used with the API ([register as a developer](https://developers.google.com/merchant/api/guides/quickstart/direct-api-calls#step_1_register_as_a_developer)). Until this is done, calls may return an error that the project is “not registered with the merchant account”. After registering, wait a few minutes before retrying.

**One project rule:** `GOOGLE_CLOUD_PROJECT_ID`, the OAuth client (`GOOGLE_CLIENT_ID`), and enabled APIs must all belong to that single GCP project. Startup logs show the configured client id hint; Settings → API Keys shows the project id.

**Error `deleted_client`:** The running server is still using a removed OAuth client. After updating `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` on the host, restart the app. Compare `GET /api/auth/oauth-debug` (returns the client id this process uses, no secrets) with the `client_id=` parameter in Google’s auth URL and with [Credentials](https://console.cloud.google.com/apis/credentials).

**Note:** Never commit `.env` or real secrets to the repo. Use your host's environment variables UI.
