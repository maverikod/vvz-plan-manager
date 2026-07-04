#!/bin/sh
# plan_manager_db/init.sh
# Idempotent database initialization for plan_manager. Invocable standalone
# or through the service wrapper. Never damages an existing database:
# every step is guarded so a re-run changes nothing once the target state
# is reached.
set -eu

PGDATA="${PGDATA:-/var/planmgr/postgres}"
PLANMGR_DB="${PLANMGR_DB:-planmgr}"
PLANMGR_DB_USER="${PLANMGR_DB_USER:-planmgr}"
PLANMGR_SECRETS="${PLANMGR_SECRETS:-/etc/planmgr/secrets/db_password}"
MIGRATIONS_DIR="${MIGRATIONS_DIR:-/opt/plan_manager_db/migrations}"

# (a) Initialize the data directory only when empty; refuse to touch a
#     non-empty directory that is not already a PostgreSQL cluster.
if [ -f "$PGDATA/PG_VERSION" ]; then
    echo "init.sh: data directory already initialized, skipping initdb"
elif [ -d "$PGDATA" ] && [ -n "$(ls -A "$PGDATA" 2>/dev/null)" ]; then
    echo "init.sh: data directory not empty and not a PostgreSQL cluster" >&2
    exit 1
else
    mkdir -p "$PGDATA"
    initdb -D "$PGDATA"
fi

# (b) The caller starts the server; this script only checks reachability.
if ! pg_isready -q; then
    echo "init.sh: PostgreSQL server is not reachable; start it before running init.sh" >&2
    exit 1
fi

# (c) Create the role when absent, with password read from the secrets file.
if [ ! -s "$PLANMGR_SECRETS" ]; then
    echo "init.sh: secrets file $PLANMGR_SECRETS is missing or empty" >&2
    exit 1
fi
PLANMGR_DB_PASSWORD="$(cat "$PLANMGR_SECRETS")"

ROLE_EXISTS="$(psql -d postgres -tAc "SELECT 1 FROM pg_roles WHERE rolname = '$PLANMGR_DB_USER'")"
if [ "$ROLE_EXISTS" = "1" ]; then
    role_created=0
else
    psql -d postgres -c "CREATE ROLE \"$PLANMGR_DB_USER\" LOGIN PASSWORD '$PLANMGR_DB_PASSWORD';"
    role_created=1
fi

# (d) Create the database when absent, owned by the role.
DB_EXISTS="$(psql -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = '$PLANMGR_DB'")"
if [ "$DB_EXISTS" = "1" ]; then
    db_created=0
else
    psql -d postgres -c "CREATE DATABASE \"$PLANMGR_DB\" OWNER \"$PLANMGR_DB_USER\";"
    db_created=1
fi

# (e) Ensure the schema_migration bookkeeping table exists.
psql -d "$PLANMGR_DB" -c "CREATE TABLE IF NOT EXISTS schema_migration (filename text PRIMARY KEY, applied_at timestamptz NOT NULL);"

# (f) Apply every pending migration in ascending filename order, each in
#     one single-transaction psql run, recording it immediately after.
applied_count=0
skipped_count=0
for migration in "$MIGRATIONS_DIR"/*.sql; do
    [ -e "$migration" ] || continue
    filename="$(basename "$migration")"
    ALREADY_APPLIED="$(psql -d "$PLANMGR_DB" -tAc "SELECT 1 FROM schema_migration WHERE filename = '$filename'")"
    if [ "$ALREADY_APPLIED" = "1" ]; then
        skipped_count=$((skipped_count + 1))
        continue
    fi
    psql -d "$PLANMGR_DB" -1 -f "$migration"
    psql -d "$PLANMGR_DB" -c "INSERT INTO schema_migration (filename, applied_at) VALUES ('$filename', now());"
    applied_count=$((applied_count + 1))
done

# (g) Report and exit successfully.
echo "init.sh: done (role_created=$role_created db_created=$db_created migrations_applied=$applied_count migrations_skipped=$skipped_count)"
exit 0
