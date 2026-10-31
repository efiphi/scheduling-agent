#!/usr/bin/env bash
# Create the chart's Kubernetes Secrets from deploy/compose/.env, for the local k3d cluster.
#   deploy/k3d/create-secrets.sh            # namespace "scheduling-agent"
#
# Each Secret gets only the keys its component needs, the same split as Compose
# (invariants 1, 7, 8): the agent never sees a database password or a Google key, the api
# never sees a Google token key. Values are never printed or passed on a command line
# (where `ps` could show them): they go through a private temporary file.
# Step 2.3 replaces this with Sealed Secrets that can live in git.
set -euo pipefail

ENV_FILE="${ENV_FILE:-deploy/compose/.env}"
NAMESPACE="${NAMESPACE:-scheduling-agent}"
[[ -f "$ENV_FILE" ]] || { echo "missing $ENV_FILE" >&2; exit 1; }

workdir="$(mktemp -d)"
chmod 700 "$workdir"
trap 'rm -rf "$workdir"' EXIT

value() {  # value KEY -> the value from .env, empty if missing
  grep -E "^$1=" "$ENV_FILE" | tail -n 1 | cut -d= -f2- || true
}

make_secret() {  # make_secret NAME KEY... : a Secret with those keys (missing ones skipped)
  local name="$1"; shift
  local file="$workdir/$name.env"
  : > "$file"
  for key in "$@"; do
    local v; v="$(value "$key")"
    [[ -n "$v" ]] && printf '%s=%s\n' "$key" "$v" >> "$file"
  done
  kubectl create secret generic "$name" --namespace "$NAMESPACE" \
    --from-env-file="$file" --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  echo "secret/$name: $(wc -l < "$file" | tr -d ' ') keys"
}

kubectl get namespace "$NAMESPACE" >/dev/null 2>&1 || kubectl create namespace "$NAMESPACE" >/dev/null

make_secret postgres POSTGRES_PASSWORD OWNER_DB_PASSWORD API_DB_PASSWORD GATEWAY_DB_PASSWORD
make_secret redis REDIS_PASSWORD
make_secret api API_DB_PASSWORD REDIS_PASSWORD GOOGLE_LOGIN_CLIENT_ID GOOGLE_LOGIN_CLIENT_SECRET \
  WEB_APP_URL WHATSAPP_ACCESS_TOKEN WHATSAPP_PHONE_NUMBER_ID WHATSAPP_APP_SECRET \
  WHATSAPP_VERIFY_TOKEN WHATSAPP_NOTIFY_TEMPLATE
make_secret gateway GATEWAY_DB_PASSWORD REDIS_PASSWORD GOOGLE_CONNECT_CLIENT_ID \
  GOOGLE_CONNECT_CLIENT_SECRET TOKEN_ENCRYPTION_KEYS
make_secret agent REDIS_PASSWORD ANTHROPIC_API_KEY AGENT_DAILY_BUDGET_USD

# Migrations connect as scheduling_owner with a URL; the password is URL-encoded, read
# from the environment rather than the command line.
OWNER_DB_PASSWORD="$(value OWNER_DB_PASSWORD)" python3 -c '
import os, urllib.parse
p = urllib.parse.quote(os.environ["OWNER_DB_PASSWORD"], safe="")
print(f"MIGRATION_DATABASE_URL=postgresql+psycopg://scheduling_owner:{p}@postgres:5432/scheduling_agent")
' > "$workdir/migrations.env"
kubectl create secret generic migrations --namespace "$NAMESPACE" \
  --from-env-file="$workdir/migrations.env" --dry-run=client -o yaml | kubectl apply -f - >/dev/null
echo "secret/migrations: 1 key"
