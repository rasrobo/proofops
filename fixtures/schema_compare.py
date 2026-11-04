#!/usr/bin/env python3
"""Compare two schema snapshots and print a single deterministic drift line.

    schema drift: 0

A table that exists in both but differs in columns, indexes or constraints counts as one
drift unit; a table present in only one side counts as one. The number is what a plan
asserts on, so it must not depend on ordering or server-specific naming.
"""

import json
import sys


def load(path):
    with open(path) as f:
        return json.load(f)


def main():
    prod = load(sys.argv[1])
    test = load(sys.argv[2])

    only_prod = set(prod["tables"]) - set(test["tables"])
    only_test = set(test["tables"]) - set(prod["tables"])

    drift = len(only_prod) + len(only_test)
    if only_prod:
        print(f"  only in production: {sorted(only_prod)[:6]}")
    if only_test:
        print(f"  only in test: {sorted(only_test)[:6]}")

    for kind in ("columns", "indexes", "constraints"):
        pa, ta = prod.get(kind, {}), test.get(kind, {})
        for t in sorted(set(prod["tables"]) & set(test["tables"])):
            a, b = pa.get(t, []), ta.get(t, [])
            if a != b:
                drift += 1
                missing = [x for x in a if x not in b]
                extra = [x for x in b if x not in a]
                print(f"  {kind} differ in {t}: missing={len(missing)} extra={len(extra)}")
                for item in missing[:2]:
                    print(f"      missing: {item}")
                for item in extra[:2]:
                    print(f"      extra:   {item}")

    print(f"tables compared: {len(prod['tables'])} (prod) / {len(test['tables'])} (rebuilt)")
    print(f"schema drift: {drift}")
    return 0 if drift == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
