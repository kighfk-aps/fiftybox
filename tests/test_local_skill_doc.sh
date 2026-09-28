#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILL="$SCRIPT_DIR/skills/fiftybox-local/SKILL.md"
PASS=0
FAIL=0
pass() { echo "PASS: $1"; PASS=$(( PASS + 1 )); }
fail() { echo "FAIL: $1"; FAIL=$(( FAIL + 1 )); }
has() { if [[ -f "$1" ]] && grep -qF -- "$2" "$1"; then pass "$3"; else fail "$3"; fi }
lacks() { if [[ -f "$1" ]] && ! grep -qF -- "$2" "$1"; then pass "$3"; else fail "$3"; fi }

has "$SKILL" "name: fiftybox-local" "SKILL.md frontmatter declares its name"

# fixed executor 3-tuple
has "$SKILL" "macstudio-gemma4" "SKILL.md names the macstudio-gemma4 provider"
has "$SKILL" "mlx-community--gemma-4-26B-A4B-it-qat-4bit" "SKILL.md names the fixed Gemma4 model id"
has "$SKILL" '`pi`' "SKILL.md dispatches with the pi agent"
has "$SKILL" "100.115.199.115:11235" "SKILL.md points at the Mac Studio mlx-serve :11235 endpoint"
has "$SKILL" "1800" "SKILL.md documents the 1800s implementation timeout"
has "$SKILL" "262,144" "SKILL.md documents the 262144 context window"
has "$SKILL" "launchctl kickstart" "SKILL.md boots the server via launchd"

# sequential execution — the executor is a single model
has "$SKILL" "순차" "SKILL.md requires sequential dispatch"
lacks "$SKILL" "서로 다른" "SKILL.md no longer spreads tasks across distinct models"
lacks "$SKILL" "동적 병렬" "SKILL.md drops the dynamic-parallel batch design"

# preflight before every dispatch
has "$SKILL" "preflight" "SKILL.md requires a server preflight"
has "$SKILL" "mlx-serve-gemma4.log" "SKILL.md polls boot progress via the mlx-serve log"
has "$SKILL" "11234" "SKILL.md watches the co-resident 8-bit lane on 11234"
has "$SKILL" "8000" "SKILL.md warns when the dormant oMLX server is up"
has "$SKILL" "tanpapa@100.115.199.115" "SKILL.md reaches the studio over SSH"
lacks "$SKILL" "Authorization: Bearer" "SKILL.md health-checks without auth (keyless mlx-serve)"

# config gate
has "$SKILL" "fiftybox-config.json" "SKILL.md reads the fiftybox-config.json settings file"
has "$SKILL" "providers.pi.backends.macstudio-gemma4" "SKILL.md gates the lane on config"

# core prohibitions
has "$SKILL" "오케스트레이터는 구현 파일을 직접 쓰거나 고치지 않는다" \
    "SKILL.md carries the no-direct-write prohibition"
has "$SKILL" "유료 모델·원격 무료 모델로 전환하지 않는다" \
    "SKILL.md refuses to fall back to other models"
has "$SKILL" "EXIT_CODE=" "SKILL.md keeps the detached-dispatch exit-code sentinel"
has "$SKILL" "태스크당 1회" "SKILL.md caps automatic retries at one per task"

# shared always-on server contract
has "$SKILL" "임의로 끄지 않는다" "SKILL.md never shuts down the resident mlx-serve lanes"

# deleted lanes must stay deleted
for gone in openrouter-free modal-qwen38 nvidia-nim turbofieldfare \
            piqwen discover_openrouter_free.py discover_free_models.py \
            qwen3.8-27b-q4_k_m gemma-4-26b-a4b-it; do
    lacks "$SKILL" "$gone" "SKILL.md no longer references $gone"
done
# retired Q4/oMLX exclusive lane must stay retired
for gone in macstudio-qwen-flash-next lmstudio-community--Qwen3.8-27B-MLX-4bit \
            macstudio-qwen38-27b qwen38-27b-8bit 100.115.199.115:8000 \
            100.115.199.115:11234 omlx\ start pi-macstudio-omlx-api-key \
            65,536; do
    lacks "$SKILL" "$gone" "SKILL.md no longer references $gone"
done
[[ ! -e "$SCRIPT_DIR/skills/fiftybox-local/scripts" ]] \
    && pass "old lane scripts directory removed" \
    || fail "skills/fiftybox-local/scripts still exists"
[[ ! -e "$SCRIPT_DIR/skills/fiftybox-local/tests" ]] \
    && pass "old lane tests directory removed" \
    || fail "skills/fiftybox-local/tests still exists"

echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]] && exit 0 || exit 1
