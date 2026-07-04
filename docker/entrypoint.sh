#!/bin/sh
# Fixed startup order for the ContainerDeployment entrypoint:
#   1. PostgreSQL      - start the database server over the mounted data
#                         directory, running initdb first if it is empty.
#   2. Readiness        - poll until PostgreSQL accepts connections.
#   3. Initialization   - run the idempotent database initializer (role,
#                         database, schema migrations); safe to re-run,
#                         refuses to damage an existing database.
#   4. Server           - exec the plan_manager server process so it
#                         replaces this shell as PID 1 and its exit status
#                         propagates to the container unchanged.
set -eu

# 1. PostgreSQL: initialize the data directory on first run (PG_VERSION is
# absent from an empty or not-yet-initialized $PGDATA), then start the
# PostgreSQL server in the background against the mounted $PGDATA,
# logging to the mounted log directory.
if [ ! -f "$PGDATA/PG_VERSION" ]; then
    initdb -D "$PGDATA"
fi
pg_ctl -D "$PGDATA" -l /var/log/planmgr/postgres.log start

# 2. Readiness: poll pg_isready once per second, up to 30 attempts. Fail
# loudly and stop the container if PostgreSQL never becomes ready.
i=0
while [ "$i" -lt 30 ]; do
    if pg_isready -q; then
        break
    fi
    i=$((i + 1))
    sleep 1
done
if [ "$i" -ge 30 ]; then
    echo "entrypoint: PostgreSQL did not become ready within 30 seconds" >&2
    exit 1
fi

# 3. Initialization: idempotent role/database/schema-migration setup
# shipped in-image at /opt/plan_manager_db/init.sh. $PGDATA is already
# initialized by step 1 above, so this script's own initdb guard is a
# no-op; it only creates the role, the database, and applies migrations,
# and refuses to act if an existing database would be damaged.
/opt/plan_manager_db/init.sh

# 4. Server: exec (not a plain call) so the server process replaces this
# shell as PID 1, receives container signals directly, and its exit code
# becomes the container's exit code.
exec python -m plan_manager.main --config /etc/planmgr/config.json
