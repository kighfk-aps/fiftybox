#!/usr/bin/env bash
# Structure tests for the unified fiftybox-execute skill
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILL="$SCRIPT_DIR/skills/fiftybox-execute/SKILL.md"
PASS=0
FAIL=0

pass() { echo "PASS: $1"; PASS=$(( PASS + 1 )); }
fail() { echo "FAIL: $1"; FAIL=$(( FAIL + 1 )); }
has() { if [[ -f "$1" ]] && grep -qF -- "$2" "$1"; then pass "$3"; else fail "$3"; fi; }
lacks() { if [[ -f "$1" ]] && ! grep -qF -- "$2" "$1"; then pass "$3"; else fail "$3"; fi; }

# --- invocation surface ---------------------------------------------------
has "$SKILL" "--provider <id>" "SKILL.md documents --provider"
has "$SKILL" "--model <id>" "SKILL.md documents --model"
has "$SKILL" "deterministic lane allocator" "SKILL.md assigns default work by lane"
has "$SKILL" "commandcode" "SKILL.md includes the CommandCode execution lane"
has "$SKILL" "zai-coding" "SKILL.md includes the Z.AI Coding Plan lane"
has "$SKILL" "glm-5.3-flash" "SKILL.md defaults Pi Coding Plan work to GLM-5.3-Flash"
has "$SKILL" "codex-write" "SKILL.md documents the writable Codex lane"
has "$SKILL" "gpt-5.6-luna" "SKILL.md assigns Codex work to GPT-5.6-luna"
has "$SKILL" "grok" "SKILL.md lists grok as a provider option"
has "$SKILL" "--implement-agent" "SKILL.md passes --implement-agent through to orchestrate.py"

# --- absorbed cc-execute contract -----------------------------------------
has "$SKILL" "design.md는 필수" "SKILL.md states design.md is mandatory"
has "$SKILL" "Out of Scope" "SKILL.md names the design doc's scope section"
has "$SKILL" "Red 페이즈 테스트 파일이 예외임을 명시한다" "SKILL.md instructs carving out Red-phase tests"
has "$SKILL" "--skip-codex-review" "SKILL.md passes --skip-codex-review to review-test"
has "$SKILL" "nohup" "SKILL.md requires detached implement runs"
has "$SKILL" "incomplete_commit" "SKILL.md warns about incomplete_commit before cleanup"
has "$SKILL" "~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py" \
    "SKILL.md uses the correct orchestrate.py path"

# --- advisory review: opt-in via natural language, no default ------------
has "$SKILL" "diff_review.py" "SKILL.md runs the generalized diff review script"
has "$SKILL" "자연어" "SKILL.md documents the natural-language opt-in trigger"
has "$SKILL" "advisory" "SKILL.md marks the review as advisory"
has "$SKILL" "테스트 실행은 Claude" "SKILL.md keeps test execution with Claude"
has "$SKILL" "Claude 폴백" "SKILL.md documents the Claude fallback"
has "$SKILL" "pathspec" "SKILL.md scopes the task diff with a pathspec"

# --- prohibitions ----------------------------------------------------------
lacks "$SKILL" "skills/orchestrate/scripts" "SKILL.md avoids the non-existent orchestrate path"
lacks "$SKILL" "errorClass" "SKILL.md omits the unimplemented errorClass table"
lacks "$SKILL" "--commit-message" "SKILL.md does not document the nonexistent --commit-message flag"

echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]] && exit 0 || exit 1
