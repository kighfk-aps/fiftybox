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

echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]] && exit 0 || exit 1
