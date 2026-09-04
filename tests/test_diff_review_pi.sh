#!/usr/bin/env bash
# Offline contract tests for diff_review_pi.py (executor swap of diff_review.py).
# Real-review E2E evidence lives in tests/fixtures/logs/ (APPROVED/BLOCKED runs
# recorded 2026-09-04 on zai-coding/glm-5.3).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REVIEW="$SCRIPT_DIR/skills/fiftybox-pi/scripts/diff_review_pi.py"
FX="$SCRIPT_DIR/skills/fiftybox-pi/tests/fixtures"
PASS=0
FAIL=0

pass() { echo "PASS: $1"; PASS=$(( PASS + 1 )); }
fail() { echo "FAIL: $1"; FAIL=$(( FAIL + 1 )); }

# 1. selftest battery (verdict parsing, findings, prompt build)
python3 "$REVIEW" --selftest | tail -1 | grep -q "PASS" \
  && pass "review selftest battery" || fail "review selftest battery"

# 2. exit-code contract
python3 "$REVIEW" >/dev/null 2>&1 && RC=0 || RC=$?
[ "$RC" -eq 2 ] && pass "missing args -> exit 2 (EXIT_ARGS)" || fail "missing args exit code: got $RC"

BAD_MODEL_EC=0
BAD_MODEL_OUT="$(python3 "$REVIEW" --diff "$FX/diff-good.diff" --spec "$FX/spec-add-greet.md" \
  --test "$FX/test-greet.py" --task-name t --out /tmp/.fbx-test-out \
  --provider no-such-provider --model whatever 2>&1)" || BAD_MODEL_EC=$?
[ "$BAD_MODEL_EC" -eq 4 ] && pass "unknown model -> exit 4 (EXIT_BAD_MODEL)" \
  || fail "bad model exit code: got $BAD_MODEL_EC"

# 3. fixtures carry the E2E evidence with the right verdicts
grep -q "판정: APPROVED" "$FX/logs/2026-09-04-fixture-good-pi-review.md" \
  && pass "recorded E2E: compliant diff -> APPROVED" || fail "good diff E2E verdict missing"
grep -qE "판정: (REVISE|BLOCKED)" "$FX/logs/2026-09-04-fixture-bad-pi-review.md" \
  && pass "recorded E2E: spec-violating diff -> REVISE/BLOCKED" || fail "bad diff E2E verdict missing"
grep -q "ValueError" "$FX/logs/2026-09-04-fixture-bad-pi-review.md" \
  && pass "recorded E2E names the missing requirement" || fail "bad diff E2E findings lack substance"

# 4. the reviewer stays read-only
grep -q 'REVIEW_TOOLS = "read,grep,find,ls"' "$REVIEW" \
  && pass "reviewer sandbox is read-only tools" || fail "reviewer tools not read-only"
REVIEW_PATH="$REVIEW" python3 - <<'PY'
import importlib.util, os, sys
spec = importlib.util.spec_from_file_location("d", os.environ["REVIEW_PATH"])
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)
assert "write" not in mod.REVIEW_TOOLS and "bash" not in mod.REVIEW_TOOLS
assert "edit" not in mod.REVIEW_TOOLS
PY
[ "$?" -eq 0 ] && pass "no write/edit/bash in the review toolset" || fail "toolset check"

# 5. exit-code parity with the original diff_review.py contract
for code in 2 3 4 5 6; do
  grep -qE "EXIT_[A-Z_]+ = $code" "$REVIEW" && pass "exit $code defined" || fail "exit $code missing"
done

echo "test_diff_review_pi: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
