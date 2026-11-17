#!/usr/bin/env bash
# Fire a real attack at the running cluster and check the whole detection path (ADR-022):
#   deploy/k3d/test-detections.sh
#
#   forged webhooks -> the api counts them -> Alloy -> Prometheus -> rule WebhookForgery fires
#   -> Alertmanager -> alert relay -> the owner's WhatsApp
#
# The attack is harmless: requests without Meta's signature, which the api refuses unread
# (T9). It only proves that such an attempt is seen and reported. The last step, the message
# arriving on the phone, is the owner's to confirm.
set -euo pipefail

WEBHOOK="${WEBHOOK:-http://127.0.0.1:8002/whatsapp/webhook}"
ATTEMPTS=6   # the rule fires at 5 in 10 minutes
TIMEOUT=360  # rules run every minute; metrics are pushed every 15 seconds

echo "Sending $ATTEMPTS unsigned webhook requests to $WEBHOOK"
for _ in $(seq "$ATTEMPTS"); do
  code=$(curl -s -o /dev/null -w '%{http_code}' -X POST -H 'Content-Type: application/json' \
    -H 'X-Hub-Signature-256: sha256=0000' --data '{}' "$WEBHOOK")
  [[ "$code" == 403 ]] || { echo "expected 403, got $code" >&2; exit 1; }
done
echo "All refused (403)."

kubectl -n observability port-forward svc/prometheus-server 19090:80 >/dev/null 2>&1 &
pf=$!
trap 'kill $pf 2>/dev/null || true' EXIT
until curl -sf -o /dev/null http://127.0.0.1:19090/-/ready; do sleep 1; done

firing() {  # is WebhookForgery firing in Prometheus?
  curl -s http://127.0.0.1:19090/api/v1/alerts \
    | python3 -c 'import json,sys; a=json.load(sys.stdin)["data"]["alerts"]; sys.exit(0 if any(x["labels"]["alertname"]=="WebhookForgery" and x["state"]=="firing" for x in a) else 1)'
}

echo "Waiting for the WebhookForgery alert (up to ${TIMEOUT}s)..."
for _ in $(seq $((TIMEOUT / 10))); do
  if firing; then
    echo "Firing in Prometheus."
    break
  fi
  sleep 10
done
firing || { echo "WebhookForgery did not fire" >&2; exit 1; }

echo "Waiting for the alert relay to send it..."
for _ in $(seq 18); do
  if kubectl -n scheduling-agent logs deploy/alert-relay --since=10m \
      | grep -q 'alerts relayed: names=WebhookForgery outcomes=\(sent\|template\)'; then
    echo "Relayed to WhatsApp. Check the phone for: \"אזהרה: בקשות מזויפות לכתובת של ווטסאפ\""
    exit 0
  fi
  sleep 10
done
echo "The relay did not send it; see: kubectl -n scheduling-agent logs deploy/alert-relay" >&2
exit 1
