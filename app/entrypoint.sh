#!/bin/sh
# Runs migrations, seeds the poll, then execs the server.
#
# Migrations run here rather than at import time so the schema is guaranteed to
# exist before the app starts answering /health. `worker` gates on that health
# check, so it only starts once the tables are real -- which is why it never pops
# a vote off the queue just to fail on a missing table.
set -e

emit() { printf '{"level":"%s","logger":"voting.entrypoint","msg":"%s"}\n' "$1" "$2"; }

apply_migrations() {
    flask db upgrade 2>/tmp/migrate.err
}

emit INFO "applying migrations"
if apply_migrations; then
    emit INFO "migrations up to date"
# A volume created before migrations existed already holds the schema that
# revision 0001 reproduces byte for byte. Stamp *0001* -- not head -- so 0002
# still runs and adds is_admin, which that schema is missing. Stamping head here
# would leave the app querying a column that was never created.
elif grep -qi "already exists" /tmp/migrate.err; then
    emit WARN "tables pre-exist from a pre-migration volume; stamping 0001"
    if ! flask db stamp 0001; then
        cat /tmp/migrate.err >&2
        emit ERROR "could not stamp revision 0001"
        exit 1
    fi
    # A second attempt now skips 0001 and applies the rest.
    if ! apply_migrations; then
        cat /tmp/migrate.err >&2
        emit ERROR "migration failed after stamping 0001"
        exit 1
    fi
    emit INFO "adopted pre-existing schema and applied pending revisions"
else
    cat /tmp/migrate.err >&2
    emit ERROR "migration failed"
    exit 1
fi

flask seed-poll

exec "$@"
