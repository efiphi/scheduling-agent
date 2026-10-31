#!/usr/bin/env bash
# Seal the chart's Secrets from deploy/compose/.env into SealedSecrets that can be committed
# (ADR-008). Run once per cluster, and again whenever a value in .env changes:
#   deploy/k3d/seal-secrets.sh     # writes deploy/cluster/secrets/k3d/*.yaml
#
# Each Secret gets only the keys its component needs, the same split as Compose
# (invariants 1, 7, 8): the agent never sees a database password or a Google key, the api
# never sees a Google token key. Plain values never reach the repository, the terminal or
# a command line (where `ps` could show them): they go through a private temporary file
# and a pipe straight into kubeseal, which encrypts them with the cluster's public key.
#
# Only this cluster's Sealed Secrets controller can decrypt the output. The default
# "strict" scope also binds each one to its name and namespace, so a SealedSecret for the
# agent cannot be renamed into the gateway's Secret. Losing the cluster loses its key; then
# run this again (nothing to back up: .env is the source).
set -euo pipefail

ENV_FILE="${ENV_FILE:-deploy/compose/.env}"
NAMESPACE="${NAMESPACE:-scheduling-agent}"
OUT_DIR="${OUT_DIR:-deploy/cluster/secrets/k3d}"
[[ -f "$ENV_FILE" ]] || { echo "missing $ENV_FILE" >&2; exit 1; }
mkdir -p "$OUT_DIR"

workdir="$(mktemp -d)"
chmod 700 "$workdir"
trap 'rm -rf "$workdir"' EXIT

value() {  # value KEY -> the value from .env, empty if missing
  grep -E "^$1=" "$ENV_FILE" | tail -n 1 | cut -d= -f2- || true
}

seal() {  # seal NAME ENV_FILE
  kubectl create secret generic "$1" --namespace "$NAMESPACE" \
    --from-env-file="$2" --dry-run=client -o yaml \
    | kubeseal --controller-namespace kube-system --format yaml > "$OUT_DIR/$1.yaml"
  echo "$OUT_DIR/$1.yaml: $(wc -l < "$2" | tr -d ' ') keys"
}

make_secret() {  # make_secret NAME KEY... : a SealedSecret with those keys (missing ones skipped)
  local name="$1"; shift
  local file="$workdir/$name.env"
  : > "$file"
  for key in "$@"; do
    local v; v="$(value "$key")"
    [[ -n "$v" ]] && printf '%s=%s\n' "$key" "$v" >> "$file"
  done
  seal "$name" "$file"
}

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
seal migrations "$workdir/migrations.env"
