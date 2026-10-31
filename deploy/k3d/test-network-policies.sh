#!/usr/bin/env bash
# Attack-style check of the NetworkPolicies on a running cluster (T21, ADR-011):
#   deploy/k3d/test-network-policies.sh
#
# From inside real pods, try every path an attacker who took over that pod would try,
# and the paths the system needs. Exits non-zero if any forbidden path is open or any
# needed path is closed. The "intruder" is a fresh pod with no labels, as if someone
# managed to start their own container in the namespace.
set -euo pipefail
NS="${NAMESPACE:-scheduling-agent}"
failures=0

# probe POD HOST PORT -> "open" or "blocked" (a TCP connect, 3-second timeout)
probe() {
  local pod="$1" host="$2" port="$3"
  if [[ "$pod" == postgres-0 || "$pod" == redis-0 ]]; then
    kubectl -n "$NS" exec "$pod" -- nc -z -w 3 "$host" "$port" >/dev/null 2>&1 && echo open || echo blocked
  else
    kubectl -n "$NS" exec "$pod" -- python -c "
import socket, sys
try:
    socket.create_connection(('$host', $port), timeout=3).close()
except OSError:
    sys.exit(1)" >/dev/null 2>&1 && echo open || echo blocked
  fi
}

expect() {  # expect WANT FROM HOST PORT WHY
  local want="$1" from="$2" host="$3" port="$4" why="$5" got
  got="$(probe "$from" "$host" "$port")"
  if [[ "$got" == "$want" ]]; then mark="ok  "; else mark="FAIL"; failures=$((failures + 1)); fi
  printf '%s %-22s -> %-26s %-8s %s\n' "$mark" "$(sed -E 's/-[a-z0-9]{8,10}-[a-z0-9]{5}$//' <<< "$from")" "$host:$port" "$got" "$why"
}

pod_of() { kubectl -n "$NS" get pod -l "app.kubernetes.io/name=$1" -o jsonpath='{.items[0].metadata.name}'; }
API="$(pod_of api)"; AGENT="$(pod_of agent)"; GATEWAY="$(pod_of google-gateway)"; EXECUTOR="$(pod_of action-executor)"

# The intruder: our agent image (it has Python), but none of our labels.
kubectl -n "$NS" run intruder --image=scheduling-agent-agent:dev --image-pull-policy=Never \
  --restart=Never --command -- sleep 300 >/dev/null
trap 'kubectl -n "$NS" delete pod intruder --now >/dev/null 2>&1 || true' EXIT
kubectl -n "$NS" wait --for=condition=Ready pod/intruder --timeout=60s >/dev/null
sleep 2  # let the policy controller learn the new pod's address (see migrations.yaml)

echo "Needed paths"
expect open    "$API"      postgres 5432 "api uses its own DB role"
expect open    "$API"      redis 6379    "sessions, queues"
expect open    "$EXECUTOR" postgres 5432 "pending actions"
expect open    "$AGENT"    redis 6379    "tasks in, plans out"
expect open    "$AGENT"    api.anthropic.com 443 "the LLM"
expect open    "$GATEWAY"  gmail.googleapis.com 443 "Google APIs"

echo "Forbidden paths"
expect blocked "$AGENT"    postgres 5432        "ADR-011: the agent has no path to the database"
expect blocked "$AGENT"    api 8000             "no pod calls another's API"
expect blocked "$AGENT"    google-gateway 8001  "the agent cannot reach the token holder"
expect blocked "$API"      google-gateway 8001  "invariant 1: api never talks to the token holder"
expect blocked "$GATEWAY"  api 8000             "no pod calls another's API"
expect blocked "$AGENT"    169.254.169.254 80   "cloud metadata (server credentials)"
expect blocked "$AGENT"    example.com 80       "only HTTPS leaves the cluster"
expect blocked postgres-0  example.com 443      "the database cannot reach the internet"
expect blocked redis-0     example.com 443      "Redis cannot reach the internet"
expect blocked intruder    postgres 5432        "an unlabeled pod reaches nothing"
expect blocked intruder    redis 6379           "an unlabeled pod reaches nothing"
expect blocked intruder    api 8000             "an unlabeled pod reaches nothing"
expect blocked intruder    example.com 443      "an unlabeled pod reaches nothing"

if (( failures > 0 )); then echo "$failures check(s) failed" >&2; exit 1; fi
echo "all checks passed"
