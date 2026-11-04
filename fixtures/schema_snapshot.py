#!/usr/bin/env python3
"""Dump a structural snapshot of whichever database Django is pointed at.

Written as JSON so two snapshots can be compared without either process needing
credentials for the other database. Run it once against production and once against the
freshly-built test database, then diff with schema_compare.py.
"""

import json
import os
import sys

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "clawway.settings")
django.setup()

from django.db import connection  # noqa: E402


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "/tmp/snapshot.json"
    cur = connection.cursor()

    cur.execute("select current_database()")
    dbname = cur.fetchone()[0]

    cur.execute(
        "select tablename from pg_tables where schemaname='public' and tablename <> 'django_migrations'"
    )
    snap = {"database": dbname, "tables": sorted(r[0] for r in cur.fetchall())}

    cur.execute(
        """
        select table_name, column_name, data_type, coalesce(character_maximum_length,0),
               is_nullable, coalesce(column_default,'')
        from information_schema.columns where table_schema='public'
        """
    )
    cols = {}
    for t, c, dt, ln, nul, dflt in cur.fetchall():
        cols.setdefault(t, []).append([c, dt, ln, nul, dflt])
    snap["columns"] = {t: sorted(v) for t, v in cols.items()}

    cur.execute("select tablename, indexdef from pg_indexes where schemaname='public'")
    idx = {}
    for t, d in cur.fetchall():
        idx.setdefault(t, []).append(d.split(" USING ", 1)[-1])
    snap["indexes"] = {t: sorted(v) for t, v in idx.items()}

    cur.execute(
        """
        select rel.relname, con.conname, con.contype
        from pg_constraint con join pg_class rel on rel.oid = con.conrelid
        join pg_namespace n on n.oid = rel.relnamespace where n.nspname='public'
        """
    )
    cons = {}
    for t, name, kind in cur.fetchall():
        cons.setdefault(t, []).append([name, kind])
    snap["constraints"] = {t: sorted(v) for t, v in cons.items()}

    with open(out, "w") as f:
        json.dump(snap, f)
    print(f"snapshot: {dbname} tables={len(snap['tables'])} -> {out}")


if __name__ == "__main__":
    main()
