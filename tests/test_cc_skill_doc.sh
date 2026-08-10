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
has "$SKILL" "qwen/qwen3.7-flash" "SKILL.md names the simple-tier model"
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

# --- Step 1 지침 (2026-08-07 E2E에서 드러난 두 가지) -----------------------
# implement는 --skip-verify를 줘도 design.md를 읽는다. 없으면 즉시 실패한다.
has "$SKILL" "design.md는 필수" "SKILL.md states design.md is mandatory"
# 설계 문서 범위 절에 Red 페이즈 테스트 예외가 없으면 Step 7의 advisory 리뷰가
# Claude가 쓴 테스트 파일을 스코프 위반으로 지적한다. 지침이 실제로 "범위 절"과
# "Red 페이즈 테스트 예외"를 함께 지시하는지 본다 — 단어 하나로는 부족하다.
has "$SKILL" "Out of Scope" "SKILL.md names the design doc's scope section"
has "$SKILL" "Red 페이즈 테스트 파일이 예외임을 명시한다" \
    "SKILL.md instructs carving out Red-phase tests in that section"
has "$SKILL" "스코프 위반" "SKILL.md explains the consequence of omitting the carve-out"

# Codex는 은퇴했다(2026-07-15 라우팅 결정). 형제 스킬들과 마찬가지로 review-test에
# --skip-codex-review를 넘겨야 한다. 빠뜨리면 매 실행마다 advisory 리뷰가 돈다.
has "$SKILL" "--skip-codex-review" "SKILL.md passes --skip-codex-review to review-test"
has "$SKILL" "Codex는 은퇴했다" "SKILL.md states why the Codex review is skipped"

# --- Step 6 GPT advisory diff 리뷰 (2026-08-10 설계) ----------------------
has "$SKILL" "cc_diff_review.py" "SKILL.md runs the diff review script"
has "$SKILL" "gpt-5.6-terra" "SKILL.md names the review-tier model"
has "$SKILL" "advisory" "SKILL.md marks the GPT review as advisory"
# 리뷰어는 read-only 샌드박스라 테스트를 돌릴 수 없다. 테스트 실행이 GPT로
# 넘어가면 "통과했다"는 근거 없는 주장을 신뢰하게 된다.
has "$SKILL" "테스트 실행은 Claude" "SKILL.md keeps test execution with Claude"
# GPT가 죽어도 파이프라인은 멈추지 않는다
has "$SKILL" "Claude 폴백" "SKILL.md documents the Claude fallback"
# 워크트리를 형제 태스크와 공유하므로 pathspec 없는 git diff는 스코프 오탐을 낳는다
has "$SKILL" "pathspec" "SKILL.md scopes the task diff with a pathspec"
# 재리뷰가 같은 날 돌면 로그에 -2가 붙는다. 경로를 조립하면 엉뚱한 파일을 읽는다
has "$SKILL" "reviewPath" "SKILL.md reads the log path from the JSON"
# 통합 검사는 GPT contract에서 out-of-scope다 — 단일 태스크 리뷰어는 형제를 못 본다
has "$SKILL" "통합 검사" "SKILL.md keeps the integration check with Claude"

echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]] && exit 0 || exit 1
