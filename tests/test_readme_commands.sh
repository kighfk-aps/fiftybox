#!/usr/bin/env bash
# README must document every slash command the installer ships.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
README="$SCRIPT_DIR/README.md"
PASS=0
FAIL=0

pass() { echo "PASS: $1"; PASS=$(( PASS + 1 )); }
fail() { echo "FAIL: $1"; FAIL=$(( FAIL + 1 )); }

# Every command file install.sh copies unconditionally must appear in README.
# The gitignored fiftybox-local* commands are excluded on purpose — a clean
# checkout does not ship them.
for cmd in fiftybox-orchestration fiftybox-plans fiftybox-execute \
           fiftybox-local fiftybox-gpt-review; do
    if grep -qF -- "/$cmd" "$README"; then
        pass "README documents /$cmd"
    else
        fail "README does not document /$cmd"
    fi
done

# The listing must be a table, not prose, so it stays scannable as commands grow.
if grep -qE '^\| *`?/fiftybox-' "$README"; then
    pass "commands are listed in a table"
else
    fail "commands are not listed in a table"
fi

# Each command needs a description, not just its name. Require the execute
# row to mention provider selection so the row carries real information.
if grep -E '^\|.*fiftybox-execute' "$README" | grep -qiE 'provider|commandcode|grok'; then
    pass "execute row describes provider parameterization"
else
    fail "execute row has no description mentioning providers"
fi

if grep -E '^\|.*fiftybox-local' "$README" | grep -qiE 'local|free|qwen'; then
    pass "local row describes local/free execution"
else
    fail "local row has no description mentioning local/free providers"
fi

# Existing content must survive.
grep -qF -- "--skip-verify" "$README" \
    && pass "existing Flags table preserved" \
    || fail "existing Flags table lost"

grep -qF -- "## How It Works" "$README" \
    && pass "existing How It Works section preserved" \
    || fail "existing How It Works section lost"

echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]] && exit 0 || exit 1
