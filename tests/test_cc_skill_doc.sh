#!/usr/bin/env bash
# Structure tests for the fiftybox-cc-execute skill document and slash command
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILL="$SCRIPT_DIR/skills/fiftybox-cc-execute/SKILL.md"
COMMAND="$SCRIPT_DIR/commands/fiftybox-cc-execute.md"
PASS=0
FAIL=0

pass() { echo "PASS: $1"; PASS=$(( PASS + 1 )); }
fail() { echo "FAIL: $1"; FAIL=$(( FAIL + 1 )); }

# has <file> <pattern> <label>
has() {
    if [[ -f "$1" ]] && grep -qF -- "$2" "$1"; then
        pass "$3"
    else
        fail "$3"
    fi
}

# lacks <file> <pattern> <label>
lacks() {
    if [[ -f "$1" ]] && ! grep -qF -- "$2" "$1"; then
        pass "$3"
    else
        fail "$3"
    fi
}

# --- 슬래시 명령 ---------------------------------------------------------
[[ -f "$COMMAND" ]] \
    && pass "slash command file exists" \
    || fail "slash command file missing"
has "$COMMAND" "name: fiftybox-cc-execute" "slash command declares its name"
has "$COMMAND" "skills/fiftybox-cc-execute/SKILL.md" "slash command points at the skill body"
has "$COMMAND" '$ARGUMENTS' "slash command forwards \$ARGUMENTS"

# --- SKILL.md 기본 ------------------------------------------------------
[[ -f "$SKILL" ]] \
    && pass "SKILL.md exists" \
    || fail "SKILL.md missing"
has "$SKILL" "name: fiftybox-cc-execute" "SKILL.md frontmatter declares its name"

# --- 필수 계약 ----------------------------------------------------------
has "$SKILL" "--implement-agent commandcode" "SKILL.md dispatches via --implement-agent commandcode"
has "$SKILL" "cc_preflight.py" "SKILL.md runs the preflight script"
has "$SKILL" "deepseek/deepseek-v4-flash" "SKILL.md names the simple-tier model"
has "$SKILL" "zai-org/glm-5.2" "SKILL.md names the complex-tier model"
has "$SKILL" "--skip-verify" "SKILL.md passes --skip-verify to implement"
has "$SKILL" "nohup" "SKILL.md requires detached implement runs"
has "$SKILL" "incomplete_commit" "SKILL.md warns about incomplete_commit before cleanup"
has "$SKILL" "~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py" \
    "SKILL.md uses the correct orchestrate.py path"

# --- 금지 사항 ----------------------------------------------------------
lacks "$SKILL" "skills/orchestrate/scripts" "SKILL.md avoids the non-existent orchestrate path"
lacks "$SKILL" "errorClass" "SKILL.md omits the unimplemented errorClass table"
lacks "$SKILL" "--output-format" "SKILL.md does not ask for JSON output format"
lacks "$SKILL" "cmd taste" "SKILL.md does not wire up taste learning"
# orchestrate.py in this lineage has no --commit-message flag; documenting it
# hands the user a command that exits 2.
lacks "$SKILL" "--commit-message" "SKILL.md does not document the nonexistent --commit-message flag"

echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]] && exit 0 || exit 1
