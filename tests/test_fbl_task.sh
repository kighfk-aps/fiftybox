#!/usr/bin/env bash
# Runs the fbl_task.py unit tests (tests/test_fbl_task.py) in repo test style.
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PASS=0
FAIL=0
pass() { echo "PASS: $1"; PASS=$(( PASS + 1 )); }
fail() { echo "FAIL: $1"; FAIL=$(( FAIL + 1 )); }

if [[ -f "$SCRIPT_DIR/skills/fiftybox-local/scripts/fbl_task.py" ]]; then
    pass "fbl_task.py exists"
else
    fail "fbl_task.py exists"
fi

if python3 -I "$SCRIPT_DIR/tests/test_fbl_task.py"; then
    pass "fbl_task.py unit tests"
else
    fail "fbl_task.py unit tests"
fi

echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]] && exit 0 || exit 1
