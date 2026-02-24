#!/bin/sh
# Infisical secret injection entrypoint (Python)
# Fetches secrets from Infisical API and injects them as env vars before starting the app.
# Required env vars: INFISICAL_CLIENT_ID, INFISICAL_CLIENT_SECRET
# Optional: INFISICAL_PROJECT_SLUG, INFISICAL_ENV (default: prod),
#           INFISICAL_URL (default: http://infisical:8080)

set -e

export INFISICAL_URL="${INFISICAL_URL:-http://infisical:8080}"
export INFISICAL_ENV="${INFISICAL_ENV:-prod}"
# IMPORTANT: Set INFISICAL_PROJECT_SLUG in your docker-compose.yml
export INFISICAL_PROJECT_SLUG="${INFISICAL_PROJECT_SLUG:?INFISICAL_PROJECT_SLUG must be set}"

if [ -z "$INFISICAL_CLIENT_ID" ] || [ -z "$INFISICAL_CLIENT_SECRET" ]; then
  echo "[infisical] No credentials set, starting without secret injection"
  exec "$@"
fi

echo "[infisical] Fetching secrets from ${INFISICAL_PROJECT_SLUG}/${INFISICAL_ENV}..."

EXPORTS=$(python3 -c "
import urllib.request, json, os, sys

base = os.environ['INFISICAL_URL']
slug = os.environ['INFISICAL_PROJECT_SLUG']
env = os.environ['INFISICAL_ENV']

try:
    data = json.dumps({'clientId': os.environ['INFISICAL_CLIENT_ID'], 'clientSecret': os.environ['INFISICAL_CLIENT_SECRET']}).encode()
    req = urllib.request.Request(f'{base}/api/v1/auth/universal-auth/login', data=data, headers={'Content-Type': 'application/json'})
    auth = json.loads(urllib.request.urlopen(req).read())
    token = auth.get('accessToken')
    if not token:
        print('[infisical] Auth failed', file=sys.stderr)
        sys.exit(1)

    req = urllib.request.Request(f'{base}/api/v3/secrets/raw?workspaceSlug={slug}&environment={env}&secretPath=/&recursive=true')
    req.add_header('Authorization', f'Bearer {token}')
    secrets = json.loads(urllib.request.urlopen(req).read())

    if 'secrets' not in secrets:
        print('[infisical] No secrets returned', file=sys.stderr)
        sys.exit(1)

    for s in secrets['secrets']:
        key = s['secretKey']
        val = s['secretValue'].replace(\"'\", \"'\\\\'\")
        print(f\"export {key}='{val}'\")
except Exception as e:
    print(f'[infisical] Error: {e}', file=sys.stderr)
    sys.exit(1)
" 2>&1) || {
  echo "[infisical] WARNING: Failed to fetch secrets, starting with existing env vars"
  exec "$@"
}

if echo "$EXPORTS" | grep -q "^export "; then
  COUNT=$(echo "$EXPORTS" | grep -c "^export ")
  eval "$EXPORTS"
  echo "[infisical] Injected ${COUNT} secrets"
else
  echo "[infisical] WARNING: $EXPORTS"
  echo "[infisical] Starting with existing env vars"
fi

exec "$@"
