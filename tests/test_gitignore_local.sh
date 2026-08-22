#!/usr/bin/env bash
# fiftybox-local (no suffix) must be trackable; fiftybox-local-execute stays ignored
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SCRIPT_DIR"
PASS=0
FAIL=0

pass() { echo "PASS: $1"; PASS=$(( PASS + 1 )); }
fail() { echo "FAIL: $1"; FAIL=$(( FAIL + 1 )); }

if git check-ignore -q "skills/fiftybox-local/SKILL.md"; then
    fail "skills/fiftybox-local/SKILL.md is still git-ignored"
else
    pass "skills/fiftybox-local/SKILL.md is trackable"
fi

if git check-ignore -q "commands/fiftybox-local.md"; then
    fail "commands/fiftybox-local.md is still git-ignored"
else
    pass "commands/fiftybox-local.md is trackable"
fi

if git check-ignore -q "skills/fiftybox-local-execute/SKILL.md"; then
    pass "skills/fiftybox-local-execute/SKILL.md remains git-ignored"
else
    fail "skills/fiftybox-local-execute/SKILL.md is no longer git-ignored"
fi

if git check-ignore -q "commands/fiftybox-local-execute.md"; then
    pass "commands/fiftybox-local-execute.md remains git-ignored"
else
    fail "commands/fiftybox-local-execute.md is no longer git-ignored"
fi

echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]] && exit 0 || exit 1
