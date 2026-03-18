# Deployment (cartozo.ai)

For production, set these **environment variables** in your hosting platform (Railway, Vercel, Render, etc.):

| Variable | Required | Description |
|----------|----------|-------------|
| `GOOGLE_CLIENT_ID` | Yes | From [Google Cloud Console](https://console.cloud.google.com/apis/credentials) |
| `GOOGLE_CLIENT_SECRET` | Yes | From same credentials |
| `DEPLOY_URL` | Yes | `https://cartozo.ai` |
| `SESSION_SECRET` | Yes | Random string, 32+ chars |

**Google Console:** Add `https://cartozo.ai/auth/google/callback` to Authorized redirect URIs and `https://cartozo.ai` to Authorized JavaScript origins.

**Note:** Never commit `.env` or real secrets to the repo. Use your host's environment variables UI.
