#!/usr/bin/env bash
# Runs the token bench unit tests (tests/test_token_bench.py): fixture validity,
# claude JSON parsing, aggregation and report. No model calls.
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PASS=0
FAIL=0
pass() { echo "PASS: $1"; PASS=$(( PASS + 1 )); }
fail() { echo "FAIL: $1"; FAIL=$(( FAIL + 1 )); }

if python3 -I "$SCRIPT_DIR/tests/test_token_bench.py"; then
    pass "token bench unit tests"
else
    fail "token bench unit tests"
fi

echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]] && exit 0 || exit 1
