#!/bin/sh
# Proves the database roles from init/01-roles.sh behave as intended.
# Runs inside the postgres container (where the role passwords are in the environment):
#   docker compose -f deploy/compose/compose.yaml exec -T postgres sh /tests/test-roles.sh
#
# Each check logs in the way a service would (over TCP, with a password) and tries
# something. "expect_fail" checks are attacks that must be refused.
set -u

DB=scheduling_agent
failures=0

# Run SQL as a given role over TCP, like a real service connection.
as_role() {
  role=$1 password=$2 sql=$3
  PGPASSWORD="$password" psql --no-psqlrc -X -q -t -A -v ON_ERROR_STOP=1 \
    -h 127.0.0.1 -U "$role" -d "$DB" -c "$sql" 2>&1
}

# Run SQL as the administrator (local socket), for inspecting the catalog.
as_admin() {
  psql --no-psqlrc -X -q -t -A -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$DB" -c "$1" 2>&1
}

expect_ok() {
  name=$1 output=$2 expected=$3
  if [ "$output" = "$expected" ]; then
    echo "PASS  $name"
  else
    echo "FAIL  $name"
    echo "      expected: $expected"
    echo "      got:      $output"
    failures=$((failures + 1))
  fi
}

expect_fail() {
  name=$1 output=$2 pattern=$3
  if echo "$output" | grep -q "$pattern"; then
    echo "PASS  $name"
  else
    echo "FAIL  $name"
    echo "      expected an error matching: $pattern"
    echo "      got: $output"
    failures=$((failures + 1))
  fi
}

# --- Services can log in, and only as themselves -----------------------------------
expect_ok "api_service can connect" \
  "$(as_role api_service "$API_DB_PASSWORD" 'SELECT current_user')" "api_service"
expect_ok "gateway_service can connect" \
  "$(as_role gateway_service "$GATEWAY_DB_PASSWORD" 'SELECT current_user')" "gateway_service"
expect_fail "api_service cannot log in with a wrong password" \
  "$(as_role api_service 'wrong-password' 'SELECT 1')" "password authentication failed"

# --- The agent has no database access at all (ADR-011) ------------------------------
expect_ok "test_t13_no_agent_role_exists" \
  "$(as_admin "SELECT count(*) FROM pg_roles WHERE rolname ILIKE '%agent%' AND rolname <> 'scheduling_agent'")" "0"
expect_fail "an 'agent' login is refused" \
  "$(as_role agent 'anything' 'SELECT 1')" "password authentication failed"

# --- No service role can escalate or bypass isolation (T13, T16) --------------------
for role in api_service gateway_service scheduling_owner; do
  expect_ok "test_t13_${role}_has_no_admin_or_rls_bypass" \
    "$(as_admin "SELECT rolsuper OR rolcreaterole OR rolcreatedb OR rolreplication OR rolbypassrls FROM pg_roles WHERE rolname = '$role'")" "f"
done

# --- Services cannot create or change structure -------------------------------------
expect_fail "api_service cannot create a table in app" \
  "$(as_role api_service "$API_DB_PASSWORD" 'CREATE TABLE app.probe (id int)')" "permission denied for schema app"
expect_fail "api_service cannot create a table in public" \
  "$(as_role api_service "$API_DB_PASSWORD" 'CREATE TABLE public.probe (id int)')" "permission denied for schema public"
expect_fail "gateway_service cannot create a table in app" \
  "$(as_role gateway_service "$GATEWAY_DB_PASSWORD" 'CREATE TABLE app.probe (id int)')" "permission denied for schema app"
expect_fail "api_service cannot create roles" \
  "$(as_role api_service "$API_DB_PASSWORD" "CREATE ROLE intruder LOGIN PASSWORD 'x'")" "permission denied to create role"

# --- Ownership: the schema belongs to the owner, not to a service -------------------
expect_ok "app schema is owned by scheduling_owner" \
  "$(as_admin "SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname = 'app'")" "scheduling_owner"
expect_ok "scheduling_owner can create in app (migrations)" \
  "$(as_role scheduling_owner "$OWNER_DB_PASSWORD" 'CREATE TABLE app.probe (id int); DROP TABLE app.probe; SELECT 1')" "1"

# --- A role without an explicit CONNECT grant is shut out ---------------------------
probe_password=$(head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n')
as_admin "CREATE ROLE probe_no_connect LOGIN PASSWORD '$probe_password'" >/dev/null
expect_fail "a role without CONNECT cannot open the database" \
  "$(as_role probe_no_connect "$probe_password" 'SELECT 1')" "permission denied for database"
as_admin "DROP ROLE probe_no_connect" >/dev/null

echo
if [ "$failures" -eq 0 ]; then
  echo "All database role checks passed."
else
  echo "$failures check(s) failed."
  exit 1
fi
