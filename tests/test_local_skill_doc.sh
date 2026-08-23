#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILL="$SCRIPT_DIR/skills/fiftybox-local/SKILL.md"
DISCOVER="$SCRIPT_DIR/skills/fiftybox-local/scripts/discover_free_models.py"
PASS=0
FAIL=0
pass() { echo "PASS: $1"; PASS=$(( PASS + 1 )); }
fail() { echo "FAIL: $1"; FAIL=$(( FAIL + 1 )); }
has() { if [[ -f "$1" ]] && grep -qF -- "$2" "$1"; then pass "$3"; else fail "$3"; fi; }

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

echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]] && exit 0 || exit 1
