#!/usr/bin/env bash
# Tests for skills/fiftybox-local/scripts/fbl_resume (fblr helper).
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PASS=0
FAIL=0
pass() { echo "PASS: $1"; PASS=$(( PASS + 1 )); }
fail() { echo "FAIL: $1"; FAIL=$(( FAIL + 1 )); }

FBLR="$SCRIPT_DIR/skills/fiftybox-local/scripts/fbl_resume"

if [[ -f "$FBLR" ]]; then
    pass "fbl_resume exists"
else
    fail "fbl_resume exists"
    echo ""
    echo "Results: $PASS passed, $FAIL failed"
    exit 1
fi
[[ -x "$FBLR" ]] && pass "fbl_resume is executable" || fail "fbl_resume is executable"

# ---------------------------------------------------------------------------
# Sandbox: two artifact dirs, newest wins; no design.md -> rejected.
# ---------------------------------------------------------------------------
SBX="$(mktemp -d)"
mkdir -p "$SBX/.omx/artifacts/orchestrate/20261014T053433Z" \
         "$SBX/.omx/artifacts/orchestrate/20261015T234452Z"
printf '# design\n' > "$SBX/.omx/artifacts/orchestrate/20261014T053433Z/design.md"
printf '# design\n' > "$SBX/.omx/artifacts/orchestrate/20261015T234452Z/design.md"
mkdir -p "$SBX/.omx/artifacts/orchestrate/20261016T000000Z"  # newest, but no design.md
cd "$SBX"

# 1. dry-run with explicit artifact dir prints the ccdx resume command
OUT="$(FBLR_DRY_RUN=1 "$FBLR" "$SBX/.omx/artifacts/orchestrate/20261014T053433Z" 2>&1)"
[[ "$OUT" == *"fiftybox-local --resume"* && "$OUT" == *"$SBX/.omx/artifacts/orchestrate/20261014T053433Z"* ]] \
    && pass "dry-run prints the resume command with the given artifact dir" \
    || fail "dry-run prints the resume command with the given artifact dir: $OUT"

# 2. no argument -> newest artifact dir WITH design.md wins (skips the invalid newest)
OUT="$(FBLR_DRY_RUN=1 "$FBLR" 2>&1)"
[[ "$OUT" == *"20261015T234452Z"* ]] \
    && pass "auto-pick selects the newest artifact dir containing design.md" \
    || fail "auto-pick selects the newest artifact dir containing design.md: $OUT"

# 3. repo with artifacts but no design.md anywhere -> clear error
rm -f "$SBX"/.omx/artifacts/orchestrate/*/design.md
OUT="$(FBLR_DRY_RUN=1 "$FBLR" 2>&1)"; RC=$?
[[ "$RC" -ne 0 && "$OUT" == *"design.md"* ]] \
    && pass "artifacts without design.md are rejected with a design.md message" \
    || fail "artifacts without design.md are rejected with a design.md message: rc=$RC $OUT"

# 4. no artifacts at all -> clear error, nonzero exit
rm -rf "$SBX/.omx"
OUT="$(FBLR_DRY_RUN=1 "$FBLR" 2>&1)"; RC=$?
[[ "$RC" -ne 0 && -n "$OUT" ]] \
    && pass "missing artifact dirs fail with a message" \
    || fail "missing artifact dirs fail with a message: rc=$RC $OUT"

# 5. nonexistent explicit dir -> clear error
OUT="$(FBLR_DRY_RUN=1 "$FBLR" "$SBX/no/such/dir" 2>&1)"; RC=$?
[[ "$RC" -ne 0 && "$OUT" == *"$SBX/no/such/dir"* ]] \
    && pass "nonexistent explicit dir fails naming the path" \
    || fail "nonexistent explicit dir fails naming the path: rc=$RC $OUT"

# 6. relative explicit dir is resolved to an absolute path in the command
mkdir -p "$SBX/.omx/artifacts/orchestrate/20261016T120000Z"
printf '# design\n' > "$SBX/.omx/artifacts/orchestrate/20261016T120000Z/design.md"
cd "$SBX"
OUT="$(FBLR_DRY_RUN=1 "$FBLR" .omx/artifacts/orchestrate/20261016T120000Z 2>&1)"
[[ "$OUT" == *"$SBX/.omx/artifacts/orchestrate/20261016T120000Z"* ]] \
    && pass "relative artifact dir is printed as an absolute path" \
    || fail "relative artifact dir is printed as an absolute path: $OUT"

rm -rf "$SBX"
echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]] && exit 0 || exit 1
