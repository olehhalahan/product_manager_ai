#!/usr/bin/env bash
# Deploy latest production code on the cartozo.ai server.
# Run from the app directory, e.g. /var/www/product_manager_ai
set -euo pipefail

BRANCH="${1:-live}"
SERVICE_NAME="${CARTOZO_SERVICE:-}"

echo "==> Working directory: $(pwd)"

echo "==> Fetch origin/${BRANCH}"
git fetch origin "${BRANCH}"

echo "==> Checkout and pull ${BRANCH}"
git checkout "${BRANCH}"
git pull origin "${BRANCH}"

COMMIT="$(git rev-parse --short HEAD)"
export DEPLOY_COMMIT="${COMMIT}"
echo "==> Deploying commit ${COMMIT}"

PIP_BIN="pip"
if [ -x ".venv/bin/pip" ]; then
  PIP_BIN=".venv/bin/pip"
elif [ -x "venv/bin/pip" ]; then
  PIP_BIN="venv/bin/pip"
fi

if [ -f requirements.txt ]; then
  echo "==> ${PIP_BIN} install -r requirements.txt"
  "${PIP_BIN}" install -r requirements.txt
fi

if [ -z "${SERVICE_NAME}" ]; then
  for candidate in cartozo product_manager_ai product-manager-ai uvicorn gunicorn; do
    if systemctl list-unit-files --type=service 2>/dev/null | awk '{print $1}' | grep -qx "${candidate}.service"; then
      SERVICE_NAME="${candidate}"
      break
    fi
  done
fi

if [ -n "${SERVICE_NAME}" ]; then
  echo "==> Restart systemd service: ${SERVICE_NAME}"
  sudo systemctl restart "${SERVICE_NAME}"
  sudo systemctl status "${SERVICE_NAME}" --no-pager || true
elif command -v supervisorctl >/dev/null 2>&1; then
  echo "==> Trying supervisorctl restart all"
  sudo supervisorctl restart all || true
else
  echo "==> Could not find systemd unit (cartozo.service not found)."
  echo "    Find the running app process:"
  echo "      ps aux | grep -E 'uvicorn|gunicorn|product_manager'"
  echo "    Or list services:"
  echo "      systemctl list-units --type=service | grep -iE 'product|uvicorn|gunicorn|cartozo'"
  echo "    Then restart manually, e.g.:"
  echo "      sudo systemctl restart <service-name>"
  echo "      # or: sudo supervisorctl restart <program>"
  exit 1
fi

echo "==> Verify deploy"
curl -fsS "https://cartozo.ai/health" | python3 -m json.tool || true
echo
echo "Open https://cartozo.ai/admin/traffic-analytics after deploy (admin login required)."
