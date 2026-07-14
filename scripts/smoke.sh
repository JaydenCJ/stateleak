#!/usr/bin/env bash
# Smoke test for stateleak: hunt the shipped demo suite, confirm the exact
# polluter/victim pair is named, verify the two-test repro, and check the
# clean path. Self-contained: pure stdlib, no network, idempotent.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"
if [ -x "$ROOT/.venv/bin/python" ]; then
  PYTHON="$ROOT/.venv/bin/python"
fi

# Zero runtime dependencies: running from src/ needs no install.
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

WORKDIR="$(mktemp -d "${TMPDIR:-/tmp}/stateleak-smoke.XXXXXX")"
trap 'rm -rf "$WORKDIR"' EXIT

fail() { echo "SMOKE FAIL: $1" >&2; exit 1; }

echo "[smoke] python: $("$PYTHON" --version 2>&1)"

DEMO="$ROOT/examples/demo_suite"
VICTIM="test_audit.AuditTests.test_warehouse_starts_empty"
POLLUTER="test_receiving.ReceivingTests.test_receiving_adds_stock"

# 1. --version matches the package version.
version_out="$("$PYTHON" -m stateleak --version)"
pkg_version="$("$PYTHON" -c 'import stateleak; print(stateleak.__version__)')"
[ "$version_out" = "stateleak $pkg_version" ] \
  || fail "--version mismatch: '$version_out' vs package '$pkg_version'"

# 2. plan is deterministic: the same seed prints the same order twice.
plan_a="$("$PYTHON" -m stateleak plan --seed 7 --runner unittest --rootdir "$DEMO")"
plan_b="$("$PYTHON" -m stateleak plan --seed 7 --runner unittest --rootdir "$DEMO")"
[ "$plan_a" = "$plan_b" ] || fail "plan output is not deterministic"
echo "$plan_a" | grep -q "$VICTIM" || fail "plan is missing the victim test"

# 3. hunt finds the exact polluter/victim pair (exit 1 = findings).
set +e
hunt_out="$("$PYTHON" -m stateleak hunt --runner unittest --rootdir "$DEMO" --trials 10)"
hunt_rc=$?
set -e
echo "$hunt_out" | sed 's/^/[hunt] /'
[ "$hunt_rc" -eq 1 ] || fail "hunt should exit 1 on findings, got $hunt_rc"
echo "$hunt_out" | grep -q "polluter -> victim" || fail "hunt did not classify a polluter"
echo "$hunt_out" | grep -q "victim   : $VICTIM" || fail "hunt did not name the victim"
echo "$hunt_out" | grep -q "polluter : $POLLUTER" || fail "hunt did not name the polluter"
echo "$hunt_out" | grep -q "minimal repro (2 tests):" || fail "repro is not minimal"

# 4. The JSON report agrees and is machine-readable.
set +e
json_out="$("$PYTHON" -m stateleak hunt --runner unittest --rootdir "$DEMO" --trials 10 --json)"
set -e
echo "$json_out" | "$PYTHON" -c "
import json, sys
data = json.load(sys.stdin)
finding = data['findings'][0]
assert data['clean'] is False
assert finding['kind'] == 'polluter'
assert finding['victim'] == '$VICTIM'
assert finding['culprits'] == ['$POLLUTER']
print('[json] polluter/victim pair confirmed')
" || fail "JSON report did not carry the pair"

# 5. verify: polluter-then-victim fails, victim-then-polluter passes.
set +e
"$PYTHON" -m stateleak verify --runner unittest --rootdir "$DEMO" \
  "$POLLUTER" "$VICTIM" >"$WORKDIR/verify.txt"
verify_rc=$?
set -e
[ "$verify_rc" -eq 1 ] || fail "verify of the repro order should exit 1"
grep -q "verify: FAIL" "$WORKDIR/verify.txt" || fail "verify did not report FAIL"
"$PYTHON" -m stateleak verify --runner unittest --rootdir "$DEMO" \
  "$VICTIM" "$POLLUTER" >/dev/null || fail "reversed order should pass"

# 6. bisect minimizes an externally captured failing order.
printf '%s\n%s\n%s\n' "$POLLUTER" \
  "test_pricing.PricingTests.test_small_orders_pay_list_price" \
  "$VICTIM" >"$WORKDIR/order.txt"
set +e
bisect_out="$("$PYTHON" -m stateleak bisect --runner unittest --rootdir "$DEMO" \
  --order-file "$WORKDIR/order.txt")"
bisect_rc=$?
set -e
[ "$bisect_rc" -eq 1 ] || fail "bisect should exit 1 on findings"
echo "$bisect_out" | grep -q "polluter : $POLLUTER" \
  || fail "bisect did not isolate the polluter from the bystander"

# 7. A clean suite exits 0 and says so.
mkdir -p "$WORKDIR/clean_suite"
cp "$DEMO/test_pricing.py" "$WORKDIR/clean_suite/"
clean_out="$("$PYTHON" -m stateleak hunt --runner unittest \
  --rootdir "$WORKDIR/clean_suite" --trials 5)" \
  || fail "hunt on a clean suite should exit 0"
echo "$clean_out" | grep -q "no order dependencies found" \
  || fail "clean suite was not reported clean"

# 8. --help lists every subcommand.
help_out="$("$PYTHON" -m stateleak --help)"
for cmd in hunt shuffle bisect verify plan; do
  echo "$help_out" | grep -q "$cmd" || fail "--help missing subcommand $cmd"
done

echo "SMOKE OK"
