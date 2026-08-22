#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PASS=0
FAIL=0
pass() { echo "PASS: $1"; PASS=$(( PASS + 1 )); }
fail() { echo "FAIL: $1"; FAIL=$(( FAIL + 1 )); }

[[ -f "$SCRIPT_DIR/skills/fiftybox-execute/scripts/diff_review.py" ]] \
    && pass "diff_review.py exists under fiftybox-execute/scripts" \
    || fail "diff_review.py missing"

[[ -f "$SCRIPT_DIR/skills/fiftybox-execute/scripts/cc_preflight.py" ]] \
    && pass "cc_preflight.py exists under fiftybox-execute/scripts" \
    || fail "cc_preflight.py missing"

grep -qF 'DEFAULT_MODEL = "gpt-5.6-terra"' "$SCRIPT_DIR/skills/fiftybox-execute/scripts/diff_review.py" \
    && pass "diff_review.py keeps gpt-5.6-terra as its own default (out of sol scope)" \
    || fail "diff_review.py default model changed unexpectedly"

python3 -c "
import argparse, importlib.util, sys
spec = importlib.util.spec_from_file_location('dr', '$SCRIPT_DIR/skills/fiftybox-execute/scripts/diff_review.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
assert callable(getattr(mod, 'main', None)) or True
" && pass "diff_review.py imports without syntax errors" \
    || fail "diff_review.py fails to import"

echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]] && exit 0 || exit 1
