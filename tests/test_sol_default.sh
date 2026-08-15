#!/usr/bin/env bash
# Tests that design/plan review defaults to gpt-5.6-sol, not gpt-5.6-terra
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GPT_REVIEW="$SCRIPT_DIR/skills/fiftybox-gpt-review/scripts/gpt_review.py"
GPT_REVIEW_SKILL="$SCRIPT_DIR/skills/fiftybox-gpt-review/SKILL.md"
ORCH="$SCRIPT_DIR/skills/fiftybox-orchestration/scripts/orchestrate.py"
PASS=0
FAIL=0

pass() { echo "PASS: $1"; PASS=$(( PASS + 1 )); }
fail() { echo "FAIL: $1"; FAIL=$(( FAIL + 1 )); }

has() {
    if [[ -f "$1" ]] && grep -qF -- "$2" "$1"; then pass "$3"; else fail "$3"; fi
}
lacks() {
    if [[ -f "$1" ]] && ! grep -qF -- "$2" "$1"; then pass "$3"; else fail "$3"; fi
}

has "$GPT_REVIEW" 'DEFAULT_MODEL = "gpt-5.6-sol"' "gpt_review.py defaults to gpt-5.6-sol"
lacks "$GPT_REVIEW" 'DEFAULT_MODEL = "gpt-5.6-terra"' "gpt_review.py no longer defaults to gpt-5.6-terra"

has "$GPT_REVIEW_SKILL" "gpt-5.6-sol" "fiftybox-gpt-review SKILL.md documents the sol default"

# orchestrate.py Phase4 design review: help text / SKIP note / docstring should
# now point at sol, not terra
has "$ORCH" "gpt-5.6-sol" "orchestrate.py mentions gpt-5.6-sol for design review"
lacks "$ORCH" "gpt-5.6-terra" "orchestrate.py no longer mentions gpt-5.6-terra anywhere"

# ---------------------------------------------------------------------------
# Repo-wide sweep: no stray gpt-5.6-terra survives outside the known-good spots.
#
# Excluded on purpose:
#   docs/, plans/            — historical design/plan/review records, frozen
#   tests/test_sol_default.sh, tests/test_diff_review_moved.sh
#                            — these assertions must name the old slug
#   skills/fiftybox-execute/scripts/diff_review.py
#                            — its own DEFAULT_MODEL; advisory diff review is
#                              explicitly out of the sol migration's scope
#   skills/fiftybox-execute/tests/test_diff_review.py
#   skills/fiftybox-gpt-review/tests/test_gpt_review.py
#   skills/fiftybox-orchestration/tests/test_gpt_review*.py
#   skills/fiftybox-orchestration/tests/test_agent_config.py
#   skills/fiftybox-orchestration/tests/test_orchestrate.py
#                            — fixtures that pass a non-default slug explicitly
#                              to exercise overrides and error messages
# ---------------------------------------------------------------------------
STRAY=""
while IFS= read -r hit; do
    case "$hit" in
        ./.git/*|./docs/*|./plans/*|./.superpowers/*|./.scratch/*) continue ;;
        */__pycache__/*) continue ;;
        ./tests/test_sol_default.sh|./tests/test_diff_review_moved.sh) continue ;;
        ./skills/fiftybox-execute/scripts/diff_review.py) continue ;;
        ./skills/fiftybox-execute/tests/*) continue ;;
        ./skills/fiftybox-gpt-review/tests/*) continue ;;
        ./skills/fiftybox-orchestration/tests/*) continue ;;
    esac
    STRAY="$STRAY $hit"
done < <(cd "$SCRIPT_DIR" && grep -rlF -- "gpt-5.6-terra" . 2>/dev/null || true)
STRAY="${STRAY# }"

if [[ -z "$STRAY" ]]; then
    pass "no stray gpt-5.6-terra left in the repo (docs/plans and known survivors excluded)"
else
    fail "stray gpt-5.6-terra found in: $(echo "$STRAY" | tr '\n' ' ')"
fi

# The two docs that used to ship the terra copy-paste example must now show sol
has "$SCRIPT_DIR/skills/fiftybox-orchestration/SKILL.md" \
    "--design-review-model gpt-5.6-sol" \
    "fiftybox-orchestration SKILL.md example uses gpt-5.6-sol"
has "$SCRIPT_DIR/skills/fiftybox-plans/SKILL.md" \
    "--design-review-model gpt-5.6-sol" \
    "fiftybox-plans SKILL.md example uses gpt-5.6-sol"

echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]] && exit 0 || exit 1
