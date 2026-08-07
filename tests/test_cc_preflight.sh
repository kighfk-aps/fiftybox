#!/usr/bin/env bash
# Tests for cc_preflight.py — never invokes the real cmd binary
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PREFLIGHT="$SCRIPT_DIR/skills/fiftybox-cc-execute/scripts/cc_preflight.py"
PASS=0
FAIL=0

# PATH를 비운 채 실행하는 케이스가 있으므로 인터프리터 경로를 미리 잡아둔다.
PY="$(command -v python3)"

pass() { echo "PASS: $1"; PASS=$(( PASS + 1 )); }
fail() { echo "FAIL: $1"; FAIL=$(( FAIL + 1 )); }

STUB_DIR="$(mktemp -d)"
FIXTURE="$STUB_DIR/models.txt"

cat > "$FIXTURE" <<'EOF'
Available models  ·  3 models

Open Source

deepseek/deepseek-v4-flash           fast hybrid-attention reasoning (default)
zai-org/glm-5.2                      powerful coding with 1M context

Anthropic

claude-sonnet-5                      best combo of speed & intelligence
EOF

cat > "$STUB_DIR/cmd" <<'EOF'
#!/usr/bin/env bash
case "$1" in
  status)
    printf 'stub status\n'
    exit "${CC_STUB_STATUS:-0}"
    ;;
  --list-models)
    cat "$CC_STUB_MODELS"
    exit "${CC_STUB_LIST_EXIT:-0}"
    ;;
esac
exit 0
EOF
chmod +x "$STUB_DIR/cmd"

# JSON 한 필드를 뽑는 헬퍼. 스크립트가 없거나 JSON이 아니면 빈 문자열을 돌려
# 단언만 실패하게 하고, 테스트 스크립트 자체는 계속 돌게 한다.
field() {
    python3 -c '
import json, sys
try:
    print(json.loads(sys.stdin.read())[sys.argv[1]])
except Exception:
    print("")
' "$1"
}

# 리스트 필드를 쉼표로 이어 붙이는 헬퍼
jlist() {
    python3 -c '
import json, sys
try:
    print(",".join(json.loads(sys.stdin.read())[sys.argv[1]]))
except Exception:
    print("")
' "$1"
}

# --- 1. cmd 미설치 -------------------------------------------------------
EMPTY_PATH_DIR="$(mktemp -d)"
set +e
OUT="$(PATH="$EMPTY_PATH_DIR" "$PY" "$PREFLIGHT" 2>/dev/null)"
RC=$?
set -e
[[ "$RC" -ne 0 ]] \
    && pass "missing cmd exits non-zero" \
    || fail "missing cmd exited 0"
[[ "$(printf '%s' "$OUT" | field status)" == "not_installed" ]] \
    && pass "missing cmd reports not_installed" \
    || fail "missing cmd status wrong: $OUT"

# --- 2. 미인증 -----------------------------------------------------------
set +e
OUT="$(PATH="$STUB_DIR:$PATH" CC_STUB_STATUS=1 CC_STUB_MODELS="$FIXTURE" \
       python3 "$PREFLIGHT" 2>/dev/null)"
RC=$?
set -e
[[ "$RC" -ne 0 ]] \
    && pass "unauthenticated exits non-zero" \
    || fail "unauthenticated exited 0"
[[ "$(printf '%s' "$OUT" | field status)" == "not_authenticated" ]] \
    && pass "unauthenticated reports not_authenticated" \
    || fail "unauthenticated status wrong: $OUT"

# --- 3. 정상 ------------------------------------------------------------
set +e
OUT="$(PATH="$STUB_DIR:$PATH" CC_STUB_STATUS=0 CC_STUB_MODELS="$FIXTURE" \
       python3 "$PREFLIGHT" \
         --require-model deepseek/deepseek-v4-flash \
         --require-model zai-org/glm-5.2 2>/dev/null)"
RC=$?
set -e
[[ "$RC" -eq 0 ]] \
    && pass "ready path exits 0" \
    || fail "ready path exited $RC: $OUT"
[[ "$(printf '%s' "$OUT" | field status)" == "ready" ]] \
    && pass "ready path reports ready" \
    || fail "ready status wrong: $OUT"

MODELS="$(printf '%s' "$OUT" | jlist models)"
[[ "$MODELS" == "deepseek/deepseek-v4-flash,zai-org/glm-5.2,claude-sonnet-5" ]] \
    && pass "model list parsed in order, headers excluded" \
    || fail "model parse wrong: $MODELS"

# --- 4. 요구 모델 누락 ---------------------------------------------------
set +e
OUT="$(PATH="$STUB_DIR:$PATH" CC_STUB_STATUS=0 CC_STUB_MODELS="$FIXTURE" \
       python3 "$PREFLIGHT" --require-model no/such-model 2>/dev/null)"
RC=$?
set -e
[[ "$RC" -ne 0 ]] \
    && pass "missing required model exits non-zero" \
    || fail "missing required model exited 0"
[[ "$(printf '%s' "$OUT" | field status)" == "missing_models" ]] \
    && pass "missing required model reports missing_models" \
    || fail "missing model status wrong: $OUT"
MISSING="$(printf '%s' "$OUT" | jlist missingModels)"
[[ "$MISSING" == "no/such-model" ]] \
    && pass "missingModels names the absent model" \
    || fail "missingModels wrong: $MISSING"

# --- 5. 목록 조회 실패 ---------------------------------------------------
set +e
OUT="$(PATH="$STUB_DIR:$PATH" CC_STUB_STATUS=0 CC_STUB_MODELS="$FIXTURE" \
       CC_STUB_LIST_EXIT=3 python3 "$PREFLIGHT" 2>/dev/null)"
RC=$?
set -e
[[ "$(printf '%s' "$OUT" | field status)" == "list_failed" ]] \
    && pass "list-models failure reports list_failed" \
    || fail "list failure status wrong: $OUT"

echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]] && exit 0 || exit 1
