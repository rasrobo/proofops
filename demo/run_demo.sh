#!/usr/bin/env bash
# The 90-second demonstration, staged. One command, three acts, no service touched.
#
#   ./demo/run_demo.sh            # with pauses, for recording
#   DEMO_FAST=1 ./demo/run_demo.sh  # no pauses, for rehearsal/CI
#
# Everything here runs against a throwaway fixture on loopback. Nothing in this script
# contacts a real host, so the recording needs no blurring.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${DEMO_PORT:-8099}"
PLAN="$ROOT/plans/claw-way-deployment.local.json"
STATE="$ROOT/fixtures/state.json"

pause() {
  [ "${DEMO_FAST:-0}" = "1" ] && return 0
  read -r -p "  ↵ $1" _ || true
  echo
}

cleanup() { [ -n "${FIXPID:-}" ] && kill "$FIXPID" 2>/dev/null || true; }
trap cleanup EXIT

if curl -s --max-time 1 "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
  echo "port ${PORT} is already serving something — a stale fixture is a false green." >&2
  echo "stop it first:  pkill -f readiness_server.py" >&2
  exit 1
fi

echo "──────────────────────────────────────────────────────────────"
echo " ACT 0 — a claim, and a plan that can disagree with it"
echo "──────────────────────────────────────────────────────────────"
python3 -m proofops list --plans "$ROOT/plans" | sed 's/^/  /'
pause "the plan is data; its revision is the contract"

python3 "$ROOT/fixtures/readiness_server.py" "$PORT" >/dev/null 2>&1 &
FIXPID=$!
sleep 1

echo
echo "──────────────────────────────────────────────────────────────"
echo " ACT 1 — the system says it is fine"
echo "──────────────────────────────────────────────────────────────"
(cd "$ROOT" && python3 -m proofops run plans/claw-way-deployment.local.json --target "http://127.0.0.1:${PORT}" --allow-local-targets)
pause "4/4. Now break it the way production actually breaks"

echo
echo "──────────────────────────────────────────────────────────────"
echo " ACT 2 — HTTP 200, and a lie inside the body"
echo "──────────────────────────────────────────────────────────────"
sed -i 's/"status": "ok"/"status": "degraded"/' "$STATE"
echo "  (injected: the app reports status=degraded; the endpoint still answers 200)"
(cd "$ROOT" && python3 -m proofops run plans/claw-way-deployment.local.json --target "http://127.0.0.1:${PORT}" --allow-local-targets) || true
pause "a status-code monitor calls that healthy. The receipt does not"

echo
echo "──────────────────────────────────────────────────────────────"
echo " ACT 3 — repair with ordinary tools, re-run the SAME plan"
echo "──────────────────────────────────────────────────────────────"
sed -i 's/"status": "degraded"/"status": "ok"/' "$STATE"
(cd "$ROOT" && python3 -m proofops run plans/claw-way-deployment.local.json --target "http://127.0.0.1:${PORT}" --allow-local-targets)
echo
echo "  same plan revision in all three runs:"
(cd "$ROOT" && python3 - <<'PY'
import json, pathlib
seen = []
for p in sorted(pathlib.Path("receipts").glob("*.json"))[-3:]:
    d = json.loads(p.read_text())
    seen.append(d["plan_revision"])
    print(f"    {d['run_id']}  {d['summary']['verdict']:10} {d['summary']['passed']}/{d['summary']['checks']}  {d['plan_revision']}")
print("    identical revision:", len(set(seen)) == 1)
PY
)
echo
echo "ProofOps repaired nothing. It proved the repair — and printed what it did not check."
