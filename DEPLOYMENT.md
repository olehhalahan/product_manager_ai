# Deployment (cartozo.ai)

For production, set these **environment variables** in your hosting platform (Railway, Vercel, Render, etc.):

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | PostgreSQL connection string, e.g. `postgresql://user:pass@host:5432/dbname` |
| `GOOGLE_CLIENT_ID` | Yes | From [Google Cloud Console](https://console.cloud.google.com/apis/credentials) |
| `GOOGLE_CLIENT_SECRET` | Yes | From same credentials |
| `DEPLOY_URL` | Yes | `https://cartozo.ai` |
| `SESSION_SECRET` | Yes | Random string, 32+ chars |

**PostgreSQL:** Create a database and set `DATABASE_URL`. Tables are created automatically on app startup. To migrate existing `data/users.json` and `data/feedback.json`, run: `python -m scripts.migrate_json_to_db`

**Google Console:** Add `https://cartozo.ai/auth/google/callback` to Authorized redirect URIs and `https://cartozo.ai` to Authorized JavaScript origins.

**Note:** Never commit `.env` or real secrets to the repo. Use your host's environment variables UI.
