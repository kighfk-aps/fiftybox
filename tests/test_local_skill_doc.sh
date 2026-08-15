#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILL="$SCRIPT_DIR/skills/fiftybox-local/SKILL.md"
COMMAND="$SCRIPT_DIR/commands/fiftybox-local.md"
DISCOVER="$SCRIPT_DIR/skills/fiftybox-local/scripts/discover_free_models.py"
PASS=0
FAIL=0
pass() { echo "PASS: $1"; PASS=$(( PASS + 1 )); }
fail() { echo "FAIL: $1"; FAIL=$(( FAIL + 1 )); }
has() { if [[ -f "$1" ]] && grep -qF -- "$2" "$1"; then pass "$3"; else fail "$3"; fi; }
lacks() { if [[ -f "$1" ]] && ! grep -qF -- "$2" "$1"; then pass "$3"; else fail "$3"; fi; }

[[ -f "$DISCOVER" ]] && pass "discover_free_models.py moved into fiftybox-local" \
    || fail "discover_free_models.py missing from fiftybox-local"

has "$SKILL" "name: fiftybox-local" "SKILL.md frontmatter declares its name"
has "$SKILL" "discover_free_models.py" "SKILL.md runs the free-model discovery script"
has "$SKILL" "modal-qwen38" "SKILL.md includes the Modal Qwen candidate"
has "$SKILL" "qwen3.8-27b-q4_k_m" "SKILL.md names the Modal Qwen model id"
has "$SKILL" "piqwen" "SKILL.md uses the piqwen agent for Modal Qwen"
has "$SKILL" "75" "SKILL.md documents the wake-up check timing"
has "$SKILL" "120" "SKILL.md documents the wake-up check timing"
has "$SKILL" "150" "SKILL.md documents the wake-up check timing"
has "$SKILL" "1800" "SKILL.md documents the 1800s local implementation timeout"

# dynamic parallelism rule
has "$SKILL" "후보 모델 수" "SKILL.md ties batch size to candidate model count"
has "$SKILL" "서로 다른" "SKILL.md requires distinct models per parallel task"

has "$SKILL" "smoke" "SKILL.md checks discovery smoke status"
has "$SKILL" "유료 모델로 임의 전환하지 않는다" "SKILL.md refuses to fall back to paid models"

has "$SKILL" "Claude는 구현 파일을 직접 쓰거나 고치지 않는다" \
    "SKILL.md carries the no-direct-write prohibition"

# --- restored operable content (was hollowed out by the cross-ref removal) ---
has "$SKILL" "~/.claude/skills/fiftybox-local/scripts/discover_free_models.py" \
    "SKILL.md gives the runnable discovery command path"
has "$SKILL" "model-choice.json" "SKILL.md records the model choice artifact"
has "$SKILL" '"history"' "SKILL.md documents the model-choice history array"

# rate-limit detection heuristic — without it 모델 소진 처리 is undetectable
has "$SKILL" "429" "SKILL.md documents the 429 rate-limit signal"
has "$SKILL" "rate limit" "SKILL.md documents the rate limit string signal"
has "$SKILL" "quota" "SKILL.md documents the quota signal"
has "$SKILL" "insufficient" "SKILL.md documents the insufficient signal"
has "$SKILL" "대소문자 무시" "SKILL.md makes the rate-limit scan case-insensitive"

# every orchestrate.py phase must be spelled out, not cross-referenced away
has "$SKILL" "--phase setup" "SKILL.md runs the setup phase"
has "$SKILL" "--phase review-test" "SKILL.md runs the review-test phase"
has "$SKILL" "--skip-codex-review" "SKILL.md passes --skip-codex-review to review-test"
has "$SKILL" "--phase complete" "SKILL.md runs the complete phase"
has "$SKILL" "--phase deploy" "SKILL.md runs the deploy phase"
has "$SKILL" "--phase cleanup" "SKILL.md runs the cleanup phase"
has "$SKILL" "incomplete_commit" "SKILL.md warns about incomplete_commit before cleanup"
has "$SKILL" "Failure Report Format" "SKILL.md carries a failure report format"

# --- Modal lane dispatch must use the agent name, not the candidate label ---
has "$SKILL" "--implement-agent piqwen --model qwen3.8-27b-q4_k_m" \
    "SKILL.md dispatches the Modal lane with the piqwen agent and its model"
has "$SKILL" "--implement-agent opencode --model" \
    "SKILL.md dispatches opencode free lanes with the opencode agent"
lacks "$SKILL" '--implement-agent "<배정된 provider>"' \
    "SKILL.md no longer substitutes the raw candidate label into --implement-agent"
lacks "$SKILL" "--implement-agent modal-qwen38" \
    "SKILL.md never passes modal-qwen38 as an agent name"

# --- no dangling references to the deleted skills ---
lacks "$SKILL" "cc-execute" "SKILL.md has no dangling cc-execute reference"
lacks "$SKILL" "free-execute" "SKILL.md has no dangling free-execute reference"

has "$COMMAND" "skills/fiftybox-local/SKILL.md" "slash command points at the skill body"
has "$COMMAND" '$ARGUMENTS' "slash command forwards \$ARGUMENTS"

echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]] && exit 0 || exit 1
