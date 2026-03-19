# Branching strategy

| Branch | Purpose | Deploy to |
|--------|---------|-----------|
| `dev` | Development, feature work, experiments | Local / staging |
| `main` | Integration, staging-ready | — |
| `live` | Production | cartozo.ai |

## Workflow

1. **Develop on `dev`** — commit and push changes to `dev`
2. **Merge to `main`** when ready for staging/integration
3. **Merge to `live`** when ready for production deploy

```bash
# Start new work
git checkout dev
git pull origin dev

# After testing, merge to main
git checkout main
git merge dev
git push origin main

# Deploy to production
git checkout live
git merge main
git push origin live
```

## Config files

| File | Purpose |
|------|---------|
| `.env` | Base config (can commit to repo if no secrets, or use env vars on server) |
| `.env.local` | Local overrides (gitignored) — copy from `.env.local.example` |
| `.env.example` | Template for all env vars |

**Local**: `.env` + `.env.local` (load order: .env first, .env.local overrides)

**Server**: Set env vars in hosting UI (DigitalOcean, etc.) — no .env files needed.
