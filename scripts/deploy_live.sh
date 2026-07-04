#!/usr/bin/env bash
# Deploy latest production code on the cartozo.ai server.
# Run from the app directory on the host (where .git and app/ live).
set -euo pipefail

BRANCH="${1:-live}"
SERVICE_NAME="${CARTOZO_SERVICE:-cartozo}"

echo "==> Fetch origin/${BRANCH}"
git fetch origin "${BRANCH}"

echo "==> Checkout and pull ${BRANCH}"
git checkout "${BRANCH}"
git pull origin "${BRANCH}"

COMMIT="$(git rev-parse --short HEAD)"
export DEPLOY_COMMIT="${COMMIT}"
echo "==> Deploying commit ${COMMIT}"

if [ -f requirements.txt ]; then
  echo "==> pip install -r requirements.txt"
  pip install -r requirements.txt
fi

if command -v systemctl >/dev/null 2>&1; then
  echo "==> Restart systemd service: ${SERVICE_NAME}"
  sudo systemctl restart "${SERVICE_NAME}"
  sudo systemctl status "${SERVICE_NAME}" --no-pager || true
else
  echo "==> Restart your process manager manually (systemctl not found)"
fi

echo "==> Verify deploy"
curl -fsS "https://cartozo.ai/health" | python3 -m json.tool || true
echo
echo "Open https://cartozo.ai/admin/traffic-analytics after deploy (admin login required)."
