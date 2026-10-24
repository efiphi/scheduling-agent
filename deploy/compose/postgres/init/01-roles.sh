#!/bin/sh
# Database roles (invariant 7, ADR-005, ADR-011). Runs once, when the data volume is empty.
#
#   scheduling_owner  owns the schema and every table; used only by migrations.
#                     Row-Level Security does not apply to a table's owner, so the
#                     services must never be the owner.
#   api_service       the api service.
#   gateway_service   the google-gateway service.
#   (no agent role)   the agent has no database access at all.
#
# Services get access table by table, with an explicit GRANT next to each table
# (Layer 1). There are deliberately no default privileges: a new table is closed
# until someone decides who may use it.
set -eu

# Passwords arrive as psql variables and are inserted with :'name', which quotes
# them as SQL literals, so a password can never break out into SQL.
psql --no-psqlrc -v ON_ERROR_STOP=1 \
  --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v owner_password="$OWNER_DB_PASSWORD" \
  -v api_password="$API_DB_PASSWORD" \
  -v gateway_password="$GATEWAY_DB_PASSWORD" <<'SQL'

-- Close Postgres defaults: by default every role may connect to every database
-- and create objects in the public schema.
REVOKE ALL ON DATABASE scheduling_agent FROM PUBLIC;
REVOKE ALL ON SCHEMA public FROM PUBLIC;

-- No role here can act as an administrator, create roles or databases,
-- replicate, or bypass Row-Level Security (T13).
CREATE ROLE scheduling_owner LOGIN
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS
  PASSWORD :'owner_password';

CREATE ROLE api_service LOGIN
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT
  CONNECTION LIMIT 20
  PASSWORD :'api_password';

CREATE ROLE gateway_service LOGIN
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT
  CONNECTION LIMIT 20
  PASSWORD :'gateway_password';

GRANT CONNECT ON DATABASE scheduling_agent TO scheduling_owner, api_service, gateway_service;

-- All application tables live in their own schema, owned by scheduling_owner.
-- Services may look inside (USAGE) but not create anything (no CREATE).
CREATE SCHEMA app AUTHORIZATION scheduling_owner;
REVOKE ALL ON SCHEMA app FROM PUBLIC;
GRANT USAGE ON SCHEMA app TO api_service, gateway_service;

ALTER ROLE scheduling_owner SET search_path = app;
ALTER ROLE api_service SET search_path = app;
ALTER ROLE gateway_service SET search_path = app;
SQL
