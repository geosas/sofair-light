#!/usr/bin/env bash
#
# _grant_api.sh - library SOURCED (not executed) by create_db.sh and
# reset_db.sh. Centralises the grants given to the least-privilege API role, so
# the two scripts can never drift apart.
#
# Prerequisites (exported by the caller): PGHOST PGPORT PGUSER PGPASSWORD
# (superuser) and the API_ROLE variable.

# Base grants + automatic CRUD on the FUTURE tables created by FROST.
# Must be applied BEFORE FROST (re)creates the tables so CRUD is auto-applied.
grant_api_base() {
    local db="$1"
    psql -d "$db" -v ON_ERROR_STOP=1 >/dev/null <<SQL
GRANT CONNECT ON DATABASE "${db}" TO "${API_ROLE}";
GRANT TEMPORARY ON DATABASE "${db}" TO "${API_ROLE}";
GRANT USAGE ON SCHEMA public TO "${API_ROLE}";
ALTER DEFAULT PRIVILEGES FOR ROLE "${PGUSER}" IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "${API_ROLE}";
SQL
}

# Explicit CRUD on the existing tables + ownership of OBSERVATIONS (required by
# the code's DISABLE TRIGGER). Returns 0 if applied, 1 if the tables are missing.
grant_api_tables() {
    local db="$1"
    if [ "$(psql -d "$db" -tAc "SELECT to_regclass('public.\"OBSERVATIONS\"') IS NOT NULL")" = "t" ]; then
        psql -d "$db" -v ON_ERROR_STOP=1 >/dev/null <<SQL
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO "${API_ROLE}";
ALTER TABLE "OBSERVATIONS" OWNER TO "${API_ROLE}";
SQL
        return 0
    fi
    return 1
}

# Waits for FROST to (re)create the OBSERVATIONS table (default ~120 s).
wait_for_observations() {
    local db="$1" tries="${2:-60}" i
    for ((i = 1; i <= tries; i++)); do
        if [ "$(psql -d "$db" -tAc "SELECT to_regclass('public.\"OBSERVATIONS\"') IS NOT NULL" 2>/dev/null)" = "t" ]; then
            return 0
        fi
        sleep 2
    done
    return 1
}
