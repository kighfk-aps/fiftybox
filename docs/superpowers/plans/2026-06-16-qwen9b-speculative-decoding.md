# Qwen3.5-9B Speculative Decoding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Ollama-based Qwen3.5-9B serving for Phase 1 (Explore) with a vLLM instance that uses ngram prompt lookup speculative decoding, utilizing the ~9GB idle VRAM during exploration.

**Architecture:** The existing Ollama GGUF (Q4 quantized, ~6.6GB) is extracted from the Ollama Docker volume and mounted into a new vLLM container on port 8001. vLLM serves it with `--speculative-model "[ngram]"`, which proposes candidate tokens from patterns already in the prompt — ideal for code summarization since file contents appear verbatim in prompts. The `select_remote_model.sh 9b` path is updated to start this container instead of Ollama.

**Tech Stack:** vLLM (Docker, already on server), GGUF format, bash, Docker cp for extraction, zsh aliases pattern (existing `9start`/`9stop` convention)

---

## File Structure

| Location | File | Change |
|----------|------|--------|
| Remote `/home/tanpapa/models/` | `qwen35-9b-q4km.gguf` | New — GGUF extracted from Ollama volume |
| Remote `~/.local/bin/` | `serve-vllm-qwen35-9b-spec.sh` | New — start/wait script |
| Remote `~/.zshrc` | aliases block | New — `9spec-start`, `9spec-stop` |
| Local `skills/fiftybox-local/scripts/` | `select_remote_model.sh` | Modify `9b` case: alias + port |
| Local `skills/fiftybox-local/scripts/` | `stop_remote_model.sh` | Modify `9b` case: alias |
| Local `skills/fiftybox-local/` | `SKILL.md` | Modify port comment in Phase 1 |
| Local `tests/` | `test_9b_spec_smoke.sh` | New — integration smoke test |

---

## Task 1: Write the Smoke Test (TDD — fails first)

**Files:**
- Create: `tests/test_9b_spec_smoke.sh`

- [ ] **Step 1: Write the test script**

```bash
#!/usr/bin/env bash
# Smoke test: verifies vLLM qwen35-9b-spec endpoint and select_remote_model.sh 9b exports.
# Run BEFORE implementation to confirm FAIL, then again after to confirm PASS.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SELECT_SCRIPT="$SCRIPT_DIR/skills/fiftybox-local/scripts/select_remote_model.sh"
REMOTE="<퇴역-GPU서버>"
PASS=0
FAIL=0

ok()   { echo "  PASS: $*"; PASS=$((PASS+1)); }
fail() { echo "  FAIL: $*"; FAIL=$((FAIL+1)); }

echo "=== select_remote_model.sh 9b: export check ==="
# We do NOT actually start the model here — just check the exported variables
# by mocking _run_alias to be a no-op and checking what gets exported.
output=$(
  bash -c '
    # Override _run_alias to be a no-op so this test does not start anything
    _run_alias() { return 0; }
    # Stub curl to return a fake model list for port 8001
    curl() { if printf "%s" "$*" | grep -q "8001"; then
      printf '"'"'{"data":[{"id":"current"}]}'"'"'; else return 1; fi; }
    export -f _run_alias curl
    FIFTYBOX_LOCAL_READY_TIMEOUT=5 bash '"$SELECT_SCRIPT"' 9b 2>/dev/null || true
  '
)

if printf "%s" "$output" | grep -q 'LOCAL_MODEL_BASE_URL=.*8001'; then
  ok "select_remote_model.sh 9b exports port 8001"
else
  fail "select_remote_model.sh 9b does not export port 8001 (got: $output)"
fi

if printf "%s" "$output" | grep -q "LOCAL_MODEL_NAME='current'"; then
  ok "select_remote_model.sh 9b exports LOCAL_MODEL_NAME=current"
else
  fail "select_remote_model.sh 9b LOCAL_MODEL_NAME mismatch (got: $output)"
fi

echo ""
echo "=== Remote endpoint check (requires container to be running) ==="
if ssh "$REMOTE" "curl -fsS --max-time 5 http://127.0.0.1:8001/v1/models" 2>/dev/null | grep -q '"id":"current"'; then
  ok "vllm-qwen35-9b-spec endpoint responds with model id=current"
else
  fail "vllm-qwen35-9b-spec not reachable at :8001 (expected after Tasks 2-5)"
fi

echo ""
echo "=== GGUF file present on remote ==="
if ssh "$REMOTE" "test -f /home/tanpapa/models/qwen35-9b-q4km.gguf && echo ok" 2>/dev/null | grep -q ok; then
  ok "GGUF file exists at /home/tanpapa/models/qwen35-9b-q4km.gguf"
else
  fail "GGUF not found at /home/tanpapa/models/qwen35-9b-q4km.gguf"
fi

echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="
[ "$FAIL" -eq 0 ]
```

- [ ] **Step 2: Make the test executable and run it to confirm it fails**

```bash
chmod +x tests/test_9b_spec_smoke.sh
bash tests/test_9b_spec_smoke.sh
```

Expected: `FAIL: select_remote_model.sh 9b does not export port 8001` (and other failures). This confirms the test is checking the right things before the implementation.

- [ ] **Step 3: Commit the test**

```bash
git add tests/test_9b_spec_smoke.sh
git commit -m "test: add smoke test for qwen35-9b vLLM spec endpoint"
```

---

## Task 2: Extract GGUF from Ollama Volume

The 9B model exists only inside the `ollama-qwen35` Docker container as an Ollama GGUF blob. We extract it to `/home/tanpapa/models/` where the vLLM containers can mount it.

**Files:**
- Remote: `/home/tanpapa/models/qwen35-9b-q4km.gguf` (new, ~6.6GB)

- [ ] **Step 1: Read the Ollama manifest to find the model blob digest**

```bash
ssh <퇴역-GPU서버> "docker exec ollama-qwen35 \
  cat /root/.ollama/models/manifests/registry.ollama.ai/library/qwen35-9b-262k-pi/latest \
  | python3 -c \"
import sys, json
m = json.load(sys.stdin)
for layer in m.get('layers', []):
    mt = layer.get('mediaType', '')
    if 'model' in mt or 'gguf' in mt.lower():
        print(layer['digest'])
        break
\""
```

Expected output: a digest string like `sha256:8015fdebef9a...` (the full hash). Note this value — call it `<DIGEST>` in the next step.

- [ ] **Step 2: Copy the GGUF blob out of the container**

Replace `<DIGEST>` with the output from Step 1:

```bash
ssh <퇴역-GPU서버> "docker cp \
  ollama-qwen35:/root/.ollama/models/blobs/<DIGEST> \
  /home/tanpapa/models/qwen35-9b-q4km.gguf"
```

This copies the ~6.6GB file. Takes 1-3 minutes. If `<DIGEST>` starts with `sha256:`, use it verbatim — Docker cp accepts the `sha256:` prefix.

- [ ] **Step 3: Verify the copy and confirm GGUF magic bytes**

```bash
ssh <퇴역-GPU서버> "
  ls -lh /home/tanpapa/models/qwen35-9b-q4km.gguf
  xxd /home/tanpapa/models/qwen35-9b-q4km.gguf | head -1
"
```

Expected: file size ~6.6G. The first line of xxd should show `4747554c` (GGUF magic bytes) somewhere in the first 4 bytes.

If the file is smaller than 1GB or xxd shows different bytes, the wrong layer was copied — rerun Step 1 and look for a layer with `"size": 6900000000` (approximately) to find the correct digest.

---

## Task 3: Create the Serve Script on Remote Server

**Files:**
- Remote: `/home/tanpapa/.local/bin/serve-vllm-qwen35-9b-spec.sh` (new)

- [ ] **Step 1: Write the serve script via SSH heredoc**

```bash
ssh <퇴역-GPU서버> "cat > /home/tanpapa/.local/bin/serve-vllm-qwen35-9b-spec.sh" << 'SCRIPT'
#!/usr/bin/env bash
set -euo pipefail

# Stop 35B vLLM if running to avoid VRAM conflict (both would exceed 24GB together)
if docker ps --format '{{.Names}}' | grep -qx vllm-qwen-35b-gptq; then
  echo "Stopping vllm-qwen-35b-gptq to free VRAM..." >&2
  docker stop vllm-qwen-35b-gptq >/dev/null
fi

docker start vllm-qwen35-9b-spec >/dev/null

for _ in $(seq 1 36); do
  body=$(curl -s http://127.0.0.1:8001/v1/models || true)
  if [[ "$body" == *'"id":"current"'* ]]; then
    echo "$body"
    exit 0
  fi
  if ! docker ps --format '{{.Names}}' | grep -qx vllm-qwen35-9b-spec; then
    echo "vllm-qwen35-9b-spec exited before becoming ready" >&2
    docker logs --tail 120 vllm-qwen35-9b-spec >&2
    exit 1
  fi
  sleep 5
done

echo "vllm-qwen35-9b-spec did not become ready on :8001 within 180s" >&2
docker logs --tail 120 vllm-qwen35-9b-spec >&2
exit 1
SCRIPT
```

- [ ] **Step 2: Make executable**

```bash
ssh <퇴역-GPU서버> "chmod +x /home/tanpapa/.local/bin/serve-vllm-qwen35-9b-spec.sh"
```

- [ ] **Step 3: Verify the file**

```bash
ssh <퇴역-GPU서버> "head -5 /home/tanpapa/.local/bin/serve-vllm-qwen35-9b-spec.sh"
```

Expected: first line `#!/usr/bin/env bash`, second line `set -euo pipefail`.

---

## Task 4: Create the Docker Container

**Files:**
- Remote: Docker container `vllm-qwen35-9b-spec` (new)

- [ ] **Step 1: Check that no container with this name already exists**

```bash
ssh <퇴역-GPU서버> "docker ps -a --filter name=vllm-qwen35-9b-spec --format '{{.Names}} {{.Status}}'"
```

Expected: empty output. If output shows the container exists, run `docker rm vllm-qwen35-9b-spec` first.

- [ ] **Step 2: Create the container**

```bash
ssh <퇴역-GPU서버> "docker create \
  --name vllm-qwen35-9b-spec \
  --gpus all \
  --network host \
  -v /home/tanpapa/models:/models \
  -v /etc/localtime:/etc/localtime \
  -e PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
  vllm/vllm-openai:latest \
    --model /models/qwen35-9b-q4km.gguf \
    --tokenizer Qwen/Qwen3.5-9B \
    --load-format gguf \
    --served-model-name current \
    --port 8001 \
    --max-model-len 131072 \
    --gpu-memory-utilization 0.80 \
    --speculative-model '[ngram]' \
    --num-speculative-tokens 5 \
    --ngram-prompt-lookup-num-tokens 4 \
    --language-model-only"
```

**Notes on key flags:**
- `/models/qwen35-9b-q4km.gguf` — the GGUF extracted in Task 2
- `--tokenizer Qwen/Qwen3.5-9B` — vLLM downloads tokenizer config files (~5MB) on first start
- `--load-format gguf` — tells vLLM to load the file as GGUF rather than HuggingFace SafeTensors
- `--max-model-len 131072` — 128K tokens; the current Ollama model uses 196K but `qwen-summary-index` env vars cap actual usage well below 128K
- `--gpu-memory-utilization 0.80` — 19.2GB reserved; GGUF Q4 weights ~6.6GB leaves ~12.6GB for KV cache
- `--speculative-model '[ngram]'` — no second model needed; finds draft tokens within the prompt itself
- `--num-speculative-tokens 5` — proposes 5 tokens per step (tunable: try 3 or 8 if quality issues arise)

- [ ] **Step 3: Verify container was created**

```bash
ssh <퇴역-GPU서버> "docker ps -a --filter name=vllm-qwen35-9b-spec --format '{{.Names}} {{.Status}} {{.Image}}'"
```

Expected: `vllm-qwen35-9b-spec Created vllm/vllm-openai:latest`

- [ ] **Step 4: Do a first-start test (pulls tokenizer, expect ~5 min)**

```bash
ssh <퇴역-GPU서버> "/home/tanpapa/.local/bin/serve-vllm-qwen35-9b-spec.sh"
```

Expected: After model loading (may take 3-8 minutes on first start as GGUF is loaded into VRAM and tokenizer downloads), prints JSON with `"id":"current"`.

If it fails with a tokenizer error like `Cannot find tokenizer`, the `--tokenizer Qwen/Qwen3.5-9B` download may require `HF_TOKEN`. In that case download the tokenizer manually:

```bash
ssh <퇴역-GPU서버> "python3 -c \"
from huggingface_hub import snapshot_download
snapshot_download(
    'Qwen/Qwen3.5-9B',
    local_dir='/home/tanpapa/models/Qwen3.5-9B-tokenizer',
    ignore_patterns=['*.safetensors', '*.bin', '*.pt', '*.gguf']
)
print('done')
\""
```

Then recreate the container replacing `--tokenizer Qwen/Qwen3.5-9B` with `--tokenizer /models/Qwen3.5-9B-tokenizer`.

- [ ] **Step 5: Stop container after successful first-start test**

```bash
ssh <퇴역-GPU서버> "docker stop vllm-qwen35-9b-spec"
```

---

## Task 5: Add Zsh Aliases on Remote Server

The `select_remote_model.sh` dispatches model starts/stops via interactive zsh aliases (same pattern as `9start`, `27start`, `35start`). We add `9spec-start` and `9spec-stop`.

**Files:**
- Remote: `~/.zshrc` (append)

- [ ] **Step 1: Check where existing model aliases are defined**

```bash
ssh <퇴역-GPU서버> "grep -n '9start\|27start\|35start' ~/.zshrc ~/.zsh_aliases 2>/dev/null | head -10"
```

Note the file where these aliases live — use that same file for the new aliases.

- [ ] **Step 2: Append the new aliases (adjust file path if aliases are in `~/.zsh_aliases`)**

```bash
ssh <퇴역-GPU서버> "cat >> ~/.zshrc" << 'ALIASES'

# qwen35-9b vLLM speculative decoding (port 8001)
alias 9spec-start='~/.local/bin/serve-vllm-qwen35-9b-spec.sh'
alias 9spec-stop='docker stop vllm-qwen35-9b-spec'
ALIASES
```

- [ ] **Step 3: Verify aliases are in the file**

```bash
ssh <퇴역-GPU서버> "grep '9spec' ~/.zshrc"
```

Expected: two lines containing `9spec-start` and `9spec-stop`.

- [ ] **Step 4: Test that the aliases work in an interactive shell**

```bash
ssh <퇴역-GPU서버> "zsh -i -c 'type 9spec-start; type 9spec-stop'"
```

Expected: output showing both aliases point to the serve script and `docker stop` command.

---

## Task 6: Update `select_remote_model.sh`

**Files:**
- Modify: `skills/fiftybox-local/scripts/select_remote_model.sh`

- [ ] **Step 1: Replace the `9b` case**

Current `9b` case (lines 27–31 in the file):
```bash
  9|9b|ollama-9b)
    echo "Starting Ollama 9B via 9start..." >&2
    _run_alias "9start"
    base_url="http://<퇴역-GPU서버>:11434/v1"
    _model_filter="9b"
```

Replace with:
```bash
  9|9b|vllm-9b)
    echo "Starting vLLM Qwen3.5-9B+ngram-spec via 9spec-start..." >&2
    _run_alias "9spec-start"
    base_url="http://<퇴역-GPU서버>:8001/v1"
    _model_filter=""
```

Use the Edit tool:

```
old_string:
  9|9b|ollama-9b)
    echo "Starting Ollama 9B via 9start..." >&2
    _run_alias "9start"
    base_url="http://<퇴역-GPU서버>:11434/v1"
    _model_filter="9b"

new_string:
  9|9b|vllm-9b)
    echo "Starting vLLM Qwen3.5-9B+ngram-spec via 9spec-start..." >&2
    _run_alias "9spec-start"
    base_url="http://<퇴역-GPU서버>:8001/v1"
    _model_filter=""
```

**Why `_model_filter=""`:** The old Ollama endpoint served multiple models and we needed to filter for "9b" in the model ID. The new vLLM container serves exactly one model named `"current"` — no filter needed, `models[0]["id"]` will be `"current"`.

**Why keep `ollama-9b` removed from the pattern:** The `ollama-9b` alias is no longer the primary path. If the user needs to start Ollama 9B manually, they can still use `9start` directly. Add `ollama-9b` back as a backward-compat alias only if needed.

- [ ] **Step 2: Verify the change looks correct**

```bash
grep -A5 "9|9b" skills/fiftybox-local/scripts/select_remote_model.sh | head -10
```

Expected: shows `9spec-start` and port `8001`.

- [ ] **Step 3: Commit**

```bash
git add skills/fiftybox-local/scripts/select_remote_model.sh
git commit -m "feat: route 9b model selection to vLLM speculative decoding container"
```

---

## Task 7: Update `stop_remote_model.sh`

**Files:**
- Modify: `skills/fiftybox-local/scripts/stop_remote_model.sh`

- [ ] **Step 1: Replace the `9b` case**

Current (lines 11–13):
```bash
  9|9b|ollama-9b)
    echo "Stopping Ollama 9B via 9stop..." >&2
    _run_alias "9stop"
```

Replace with:
```bash
  9|9b|vllm-9b)
    echo "Stopping vLLM Qwen3.5-9B+spec via 9spec-stop..." >&2
    _run_alias "9spec-stop"
```

- [ ] **Step 2: Verify**

```bash
grep -A3 "9|9b" skills/fiftybox-local/scripts/stop_remote_model.sh | head -6
```

Expected: shows `9spec-stop`.

- [ ] **Step 3: Commit**

```bash
git add skills/fiftybox-local/scripts/stop_remote_model.sh
git commit -m "feat: route 9b stop to vLLM speculative decoding container"
```

---

## Task 8: Update `SKILL.md` Port Reference

**Files:**
- Modify: `skills/fiftybox-local/SKILL.md`

- [ ] **Step 1: Find and update the Phase 1 port reference**

In `SKILL.md`, the failure reporting section at line ~99 shows:
```
로컬 GPU 엔드포인트(<퇴역-GPU서버>:8000)에서 사용 가능한 모델을 조회하지 못했습니다.
```

This is in the Phase 1 failure block. Update to reference port 8001:

```
old_string:
로컬 GPU 엔드포인트(<퇴역-GPU서버>:8000)에서 사용 가능한 모델을 조회하지 못했습니다.
<퇴역-GPU서버>에서 선택한 모델이 올라가 있고 OpenAI 호환 서버가 /v1/models를 노출하는지 확인하세요.

new_string:
로컬 GPU 엔드포인트(<퇴역-GPU서버>:8001)에서 사용 가능한 모델을 조회하지 못했습니다.
<퇴역-GPU서버>에서 vllm-qwen35-9b-spec 컨테이너가 올라가 있고 OpenAI 호환 서버가 :8001/v1/models를 노출하는지 확인하세요.
```

- [ ] **Step 2: Commit**

```bash
git add skills/fiftybox-local/SKILL.md
git commit -m "docs: update Phase 1 endpoint reference from port 8000 to 8001"
```

---

## Task 9: Run Smoke Test and Verify End-to-End

- [ ] **Step 1: Start the container and run the smoke test**

```bash
# Start the container on the remote server first
ssh <퇴역-GPU서버> "/home/tanpapa/.local/bin/serve-vllm-qwen35-9b-spec.sh"
# Then run the full smoke test
bash tests/test_9b_spec_smoke.sh
```

Expected:
```
=== select_remote_model.sh 9b: export check ===
  PASS: select_remote_model.sh 9b exports port 8001
  PASS: select_remote_model.sh 9b exports LOCAL_MODEL_NAME=current

=== Remote endpoint check (requires container to be running) ===
  PASS: vllm-qwen35-9b-spec endpoint responds with model id=current

=== GGUF file present on remote ===
  PASS: GGUF file exists at /home/tanpapa/models/qwen35-9b-q4km.gguf

=== Results: 4 passed, 0 failed ===
```

- [ ] **Step 2: Verify the `stop_remote_model.sh 9b` path**

```bash
bash skills/fiftybox-local/scripts/stop_remote_model.sh 9b
```

Expected: `Stopping vLLM Qwen3.5-9B+spec via 9spec-stop...`
The call goes through `_run_alias "9spec-stop"` which runs `docker stop vllm-qwen35-9b-spec`.

- [ ] **Step 3: Optional — run `qwen-summary-index --dry-run` against a small project to confirm pipeline compatibility**

```bash
# Start the container again
ssh <퇴역-GPU서버> "/home/tanpapa/.local/bin/serve-vllm-qwen35-9b-spec.sh"

# Source the env vars that the skill would set
eval "$(bash skills/fiftybox-local/scripts/select_remote_model.sh 9b)"

# Dry-run the explorer against this repo (doesn't call the model)
python3 /Users/tanpapa/Desktop/develop-a/local-model/bin/qwen-summary-index \
  "$(pwd)" \
  --context-tier 256k \
  --model "$LOCAL_MODEL_NAME" \
  --dry-run

# Stop the container
bash skills/fiftybox-local/scripts/stop_remote_model.sh 9b
unset QWEN_SUMMARY_BASE_URL QWEN_SUMMARY_MODEL QWEN_SUMMARY_API_KEY LOCAL_MODEL_BASE_URL LOCAL_MODEL_API_KEY LOCAL_MODEL_NAME
```

Expected: dry-run writes prompt files to `runs/<timestamp>/summary/` without calling the model. Confirms env var wiring is correct.

- [ ] **Step 4: Commit the final state**

```bash
git add tests/test_9b_spec_smoke.sh
git commit -m "test: pass smoke test for qwen35-9b vLLM spec endpoint" --allow-empty
```

(If `test_9b_spec_smoke.sh` was already committed in Task 1, this step is a no-op — skip if `git status` is clean.)

---

## Tuning Reference (post-implementation)

Once running, if the speculative decoding acceptance rate is low (visible in vLLM logs as `spec_token_acceptance_rate`):

- **Lower `--num-speculative-tokens`** from 5 to 3 — safer proposals, higher acceptance
- **Raise `--ngram-prompt-lookup-num-tokens`** from 4 to 6 — longer context for matching
- **Upgrade to draft model** — replace `--speculative-model '[ngram]'` with `--speculative-model Qwen/Qwen3-0.5B` (~400MB download to `/home/tanpapa/models/`); remove `--ngram-prompt-lookup-num-tokens`
