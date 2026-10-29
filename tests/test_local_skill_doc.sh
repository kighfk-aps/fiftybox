#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILL="$SCRIPT_DIR/skills/fiftybox-local/SKILL.md"
REF="$SCRIPT_DIR/skills/fiftybox-local/reference.md"
YAML="$SCRIPT_DIR/skills/fiftybox-local/agents/openai.yaml"
PASS=0
FAIL=0
pass() { echo "PASS: $1"; PASS=$(( PASS + 1 )); }
fail() { echo "FAIL: $1"; FAIL=$(( FAIL + 1 )); }
has() { if [[ -f "$1" ]] && grep -qF -- "$2" "$1"; then pass "$3"; else fail "$3"; fi }
lacks() { if [[ -f "$1" ]] && ! grep -qF -- "$2" "$1"; then pass "$3"; else fail "$3"; fi }

has "$SKILL" "name: fiftybox-local" "SKILL.md frontmatter declares its name"

# fixed executor 4-tuple
has "$SKILL" "macstudio-qwen-flash-next" "SKILL.md names the Flash-Next provider"
has "$SKILL" "Jundot--Qwen3.8-Flash-Next-oQ4e-mtp" "SKILL.md names the fixed Flash-Next model id"
has "$SKILL" '`pi`' "SKILL.md dispatches with the pi agent"
has "$SKILL" "100.115.199.115:8000" "SKILL.md points at the Mac Studio oMLX :8000 endpoint"
has "$SKILL" "macstudio-omlx.key" "SKILL.md documents the oMLX API key file"
has "$SKILL" "1800" "SKILL.md documents the 1800s implementation timeout"
has "$SKILL" "262,144" "SKILL.md documents the 262144 context window"

# sequential execution — the executor is a single model
has "$SKILL" "순차" "SKILL.md requires sequential dispatch"
lacks "$SKILL" "동적 병렬" "SKILL.md drops the dynamic-parallel batch design"
# Claude-usage contract: one script call per batch, no polling turns
has "$SKILL" "fbl_task.py" "SKILL.md drives the loop through fbl_task.py"
has "$SKILL" "run_in_background" "SKILL.md runs the batch as a background task"
has "$SKILL" "폴링 금지" "SKILL.md forbids polling turns"
lacks "$SKILL" "30~60초 간격" "SKILL.md no longer asks for 30-60s polling"
has "$SKILL" "새 세션" "SKILL.md tells the orchestrator to run in a fresh session"
has "$SKILL" "compact" "SKILL.md offers /compact before requiring a new session"
has "$SKILL" "fblr" "SKILL.md offers the fblr one-word resume helper"
has "$SKILL" "묶음" "SKILL.md reviews in batches"
has "$SKILL" "preflight" "SKILL.md requires a server preflight"
has "$SKILL" "DESIGN_MD_MAX_LINES" "SKILL.md documents the design size limit"
has "$SKILL" "PROMPT_MAX_LINES" "SKILL.md documents the prompt size gate"
has "$SKILL" "reference.md" "SKILL.md points at reference.md for failure-only detail"

# config gate
has "$SKILL" "fiftybox-config.json" "SKILL.md reads the fiftybox-config.json settings file"
has "$SKILL" "providers.pi.backends.macstudio-qwen-flash-next" "SKILL.md gates the lane on config"

# core prohibitions
has "$SKILL" "오케스트레이터는 구현 파일을 직접 쓰거나 고치지 않는다" \
    "SKILL.md carries the no-direct-write prohibition"
has "$SKILL" "유료 모델·원격 무료 모델로 전환하지 않는다" \
    "SKILL.md refuses to fall back to other models"
has "$SKILL" "EXIT_CODE=" "SKILL.md keeps the exit-code sentinel"
has "$SKILL" "태스크당 1회" "SKILL.md caps automatic retries at one per task"
has "$SKILL" "임의로 끄지 않는다" "SKILL.md never shuts down the resident lanes"

# the ioh lane is a pool lane beside the studio lane
has "$SKILL" "iq3s" "SKILL.md names the ioh iq3s pool lane"
lacks "$SKILL" "사용자 지시가 있을 때만" "SKILL.md drops the user-directed-only ioh gate"
has "$REF" "레인 풀: ioh" "reference.md documents the ioh pool lane"

# served-model lanes: the full candidate table lives in reference.md, SKILL.md stays compact
has "$REF" "macstudio-gemma4" "reference.md lists gemma4 as an ordinary Studio candidate"
has "$REF" "ioh-gemma31b" "reference.md lists the ioh Gemma-31B candidate"
has "$REF" "ioh-qwen27b" "reference.md lists the ioh Qwen3.8-27B candidate"
has "$REF" "RTX 5060 Ti" "reference.md says the 5060 Ti (8081) is not a lane"
has "$REF" "SKIP=" "reference.md documents the preflight SKIP= line"
has "$SKILL" "R9700" "SKILL.md limits ioh to the R9700"
has "$SKILL" "PICK=" "SKILL.md shows the preflight PICK= line"
has "$SKILL" "NO_CANDIDATES" "SKILL.md documents the NO_CANDIDATES stop"
has "$SKILL" "후보 표" "SKILL.md names the candidate table"
lacks "$SKILL" "benchmark-only" "SKILL.md has no benchmark-only lane"
lacks "$REF" "benchmark-only" "reference.md has no benchmark-only lane"
lacks "$SKILL" "LANE_POOL" "SKILL.md no longer mentions the fixed pool constant"
lacks "$REF" "LANE_POOL" "reference.md no longer mentions the fixed pool constant"

# lane-pool contract: dependency declaration, per-lane output, moves
has "$SKILL" "Depends:" "SKILL.md documents the Depends: declaration"
has "$SKILL" "LANE=" "SKILL.md shows the LANE= output field"
has "$SKILL" "MOVED=" "SKILL.md shows the MOVED= output field"
has "$SKILL" "ALL_LANES_DOWN" "SKILL.md documents the ALL_LANES_DOWN stop"

# size guard: the skill is re-read on every orchestrator turn
LINES=$(wc -l < "$SKILL" | tr -d ' ')
if [[ "$LINES" -le 230 ]]; then pass "SKILL.md is $LINES lines (<= 230)"; else fail "SKILL.md is $LINES lines (> 230)"; fi

# reference.md carries what only matters on failure
has "$REF" "omlx start" "reference.md documents the server start procedure"
has "$REF" "lsof" "reference.md documents the lane check"
has "$REF" "Calibration" "reference.md keeps the calibration rule"

# deleted lanes must stay deleted
for gone in openrouter-free modal-qwen38 nvidia-nim turbofieldfare \
            piqwen discover_openrouter_free.py discover_free_models.py \
            qwen3.8-27b-q4_k_m gemma-4-26b-a4b-it; do
    lacks "$SKILL" "$gone" "SKILL.md no longer references $gone"
done

# scripts: the single batch driver exists, old discovery scripts stay gone
[[ -f "$SCRIPT_DIR/skills/fiftybox-local/scripts/fbl_task.py" ]] \
    && pass "fbl_task.py exists" \
    || fail "fbl_task.py missing"
[[ ! -e "$SCRIPT_DIR/skills/fiftybox-local/scripts/discover_free_models.py" \
   && ! -e "$SCRIPT_DIR/skills/fiftybox-local/scripts/discover_openrouter_free.py" ]] \
    && pass "old discovery scripts removed" \
    || fail "old discovery scripts still exist"
[[ ! -e "$SCRIPT_DIR/skills/fiftybox-local/tests" ]] \
    && pass "old lane tests directory removed" \
    || fail "skills/fiftybox-local/tests still exists"

# Codex metadata describes the current executor
has "$YAML" "Flash-Next" "openai.yaml names the Flash-Next executor"
lacks "$YAML" "Gemma4-26B-A4B" "openai.yaml no longer names the retired Gemma4 executor"

echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]] && exit 0 || exit 1
