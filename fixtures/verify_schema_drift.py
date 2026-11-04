#!/usr/bin/env python3
"""Structural comparison between a freshly-built test database and production.

The migration-replay check used to compare only `count(*) from pg_tables`. That would
pass a database with the right 182 table names and the wrong columns in every one of
them, which is not the claim anyone actually cares about.

This compares, per table:
  * the set of column names and their data types
  * the set of index definitions (normalised, so `CREATE INDEX a ON t USING btree (c)`
    from one server equals the same from another)
  * the set of constraint names and kinds

It prints one deterministic line for the plan to assert on:

    schema drift: 0

Run:  python3 verify_schema_drift.py            (inside the web container)
"""

import os
import sys

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "clawway.settings")

PROD = "hub_store"
TEST = "test_sqs_test_db"


def tables(cur, db):
    cur.execute(
        "select tablename from pg_tables where schemaname='public' and tablename <> 'django_migrations'"
    )
    return {r[0] for r in cur.fetchall() if r[0]}


def columns(cur, db):
    cur.execute(
        """
        select table_name, column_name, data_type, coalesce(character_maximum_length, 0),
               is_nullable, coalesce(column_default, '')
        from information_schema.columns
        where table_schema='public'
        """
    )
    out = {}
    for t, c, dt, ln, nul, dflt in cur.fetchall():
        out.setdefault(t, set()).add((c, dt, ln, nul, dflt))
    return out


def indexes(cur, db):
    cur.execute(
        """
        select tablename, indexdef from pg_indexes where schemaname='public'
        """
    )
    out = {}
    for t, d in cur.fetchall():
        # strip the per-database name prefix noise but keep the definition
        out.setdefault(t, set()).add(d.split(" USING ", 1)[-1])
    return out


def constraints(cur, db):
    cur.execute(
        """
        select rel.relname, con.conname, con.contype
        from pg_constraint con join pg_class rel on rel.oid = con.conrelid
        join pg_namespace n on n.oid = rel.relnamespace
        where n.nspname='public'
        """
    )
    out = {}
    for t, name, kind in cur.fetchall():
        out.setdefault(t, set()).add((name, kind))
    return out


def snapshot(db):
    django.setup()
    from django.db import connections

    alias = "default"
    conn = connections[alias]
    if db != PROD:
        # point the same connection at the test database for this comparison
        conn.close()
        conn.settings_dict["NAME"] = db
    cur = conn.cursor()
    snap = {
        "tables": tables(cur, db),
        "columns": columns(cur, db),
        "indexes": indexes(cur, db),
        "constraints": constraints(cur, db),
    }
    return snap


def main():
    prod = snapshot(PROD)
    test = snapshot(TEST)

    drift = 0
    only_prod = prod["tables"] - test["tables"]
    only_test = test["tables"] - prod["tables"]
    drift += len(only_prod) + len(only_test)
    if only_prod:
        print(f"  only in production: {sorted(only_prod)[:5]}")
    if only_test:
        print(f"  only in test: {sorted(only_test)[:5]}")

    for kind in ("columns", "indexes", "constraints"):
        for t in sorted(prod["tables"] & test["tables"]):
            a = prod[kind].get(t, set())
            b = test[kind].get(t, set())
            if a != b:
                drift += 1
                missing = a - b
                extra = b - a
                print(f"  {kind} differ in {t}: missing={len(missing)} extra={len(extra)}")
                for item in list(missing)[:2]:
                    print(f"      missing: {item}")
                for item in list(extra)[:2]:
                    print(f"      extra:   {item}")

    print(f"tables compared: {len(prod['tables'])} / {len(test['tables'])}")
    print(f"schema drift: {drift}")
    return 0 if drift == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
