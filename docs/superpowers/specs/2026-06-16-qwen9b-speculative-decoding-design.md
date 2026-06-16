# Design: Qwen3.5-9B vLLM Speculative Decoding for Explore Phase

**Date:** 2026-06-16  
**Status:** Approved

## Summary

Replace the Ollama-based Qwen3.5-9B serving for Phase 1 (Explore) with a vLLM instance that uses ngram prompt lookup decoding. No new model downloads are required. The change is contained to the `9b` selection path in the helper scripts and a new Docker container.

## Background

During `fiftybox-local` Phase 1, the `qwen-summary-index` pipeline runs `qwen35-9b-262k-pi` via Ollama (`ollama-qwen35` container, port 11435). Ollama does not support speculative decoding. The RTX 3090 Ti (24GB) has ~9GB VRAM idle during this phase, which goes unused.

vLLM already runs on the same machine for the 35B implementation model (container `vllm-qwen-35b-gptq`, port 8000). The vLLM image is available. The original Qwen3.5-9B BF16 weights exist at `/home/tanpapa/models/hub/models--Qwen--Qwen3.5-9B`.

Phase 1 (Explore) and Phase 5 (Implement) never run simultaneously, so port 8001 can be dedicated to the 9B vLLM container without conflict.

## Approach: Ngram Prompt Lookup Decoding

**Why ngram over a draft model:** `qwen-summary-index` sends file contents in the prompt and asks the model to summarize them. The model's output often re-uses identifiers, function names, and tokens already present in the prompt. Ngram lookup exploits this directly — no download, no VRAM for a second model, and it works without tokenizer alignment constraints.

vLLM implements this as `--speculative-model [ngram]`, which:
1. Scans the current prompt for n-gram matches to the last K generated tokens
2. Proposes the next `--num-speculative-tokens` tokens from that match
3. The main model verifies all proposals in a single forward pass

Expected speedup for code summarization prompts: **1.5–2×**.

**Future upgrade path:** If ngram gains are insufficient, replace `--speculative-model [ngram]` with `--speculative-model Qwen/Qwen3-0.5B` (~400MB). Architecture is compatible; same tokenizer family.

## Components

### 1. New Docker container: `vllm-qwen35-9b-spec`

```bash
docker create \
  --name vllm-qwen35-9b-spec \
  --gpus all \
  --network host \
  -v /home/tanpapa/models:/root/.cache/huggingface \
  -v /etc/localtime:/etc/localtime \
  -e PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
  vllm/vllm-openai:latest \
    --model Qwen/Qwen3.5-9B \
    --served-model-name current \
    --port 8001 \
    --dtype bfloat16 \
    --quantization fp8 \
    --kv-cache-dtype fp8 \
    --max-model-len 131072 \
    --gpu-memory-utilization 0.80 \
    --speculative-model "[ngram]" \
    --num-speculative-tokens 5 \
    --ngram-prompt-lookup-num-tokens 4 \
    --enable-chunked-prefill \
    --language-model-only
```

**VRAM estimate:** FP8 9B weights ≈9GB + KV cache at `gpu-memory-utilization 0.80` ≈ 9–10GB. Total ≈ 18–19GB, well under 24GB.

**Context length:** 131072 (128K). The current Ollama model allows 196608 but `qwen-summary-index` env vars cap per-file and batch sizes far below 128K; this is sufficient.

### 2. New serve script: `/home/tanpapa/.local/bin/serve-vllm-qwen35-9b-spec.sh`

Follows the same pattern as `serve-vllm-current`:
- Stop `vllm-qwen-35b-gptq` if running (prevent VRAM conflict)
- Start `vllm-qwen35-9b-spec`
- Poll `http://127.0.0.1:8001/v1/models` until `"id":"current"` appears (timeout 180s)
- Print model list on success, print docker logs + exit 1 on failure

### 3. New zsh aliases on `<퇴역-GPU서버>`

Add to `~/.zshrc` (or `~/.zsh_aliases`):

```bash
alias 9spec-start='~/.local/bin/serve-vllm-qwen35-9b-spec.sh'
alias 9spec-stop='docker stop vllm-qwen35-9b-spec'
```

### 4. `select_remote_model.sh` — modify `9b` case

```bash
# Before:
9|9b|ollama-9b)
  _run_alias "9start"
  base_url="http://<퇴역-GPU서버>:11434/v1"
  _model_filter="9b"

# After:
9|9b|vllm-9b)
  echo "Starting vLLM Qwen3.5-9B+spec via 9spec-start..." >&2
  _run_alias "9spec-start"
  base_url="http://<퇴역-GPU서버>:8001/v1"
  _model_filter=""
```

The `_model_filter` is cleared because vLLM serves the model as `"current"` (exact match, no filter needed).

Backward compat: add `ollama-9b` as a legacy alias for the old Ollama path (optional, for manual use).

### 5. `stop_remote_model.sh` — modify `9b` case

```bash
# Before:
9|9b|ollama-9b)
  _run_alias "9stop"

# After:
9|9b|vllm-9b)
  echo "Stopping vLLM Qwen3.5-9B+spec via 9spec-stop..." >&2
  _run_alias "9spec-stop"
```

### 6. `fiftybox-local/SKILL.md` — update endpoint reference

The health-check snippet in the SKILL.md currently shows port 8000. Update the Phase 1 exploration endpoint comment to reference port 8001.

## Sequence

```
Phase 1 start
  → select_remote_model.sh 9b
    → 9spec-start (serve-vllm-qwen35-9b-spec.sh)
      → stops vllm-qwen-35b-gptq if running
      → starts vllm-qwen35-9b-spec
      → polls :8001/v1/models → "current" ready
    → exports LOCAL_MODEL_BASE_URL=http://<퇴역-GPU서버>:8001/v1
    → exports QWEN_SUMMARY_BASE_URL, LOCAL_MODEL_NAME=current, etc.
  → qwen-summary-index runs against :8001 (vLLM + ngram spec decoding)
  → Phase 1 complete
  → stop_remote_model.sh 9b
    → 9spec-stop → docker stop vllm-qwen35-9b-spec
  → unset QWEN_SUMMARY_* env vars

Phase 5 start (unchanged)
  → select_remote_model.sh 27b|35b → :8000
```

## What Does NOT Change

- `qwen-summary-index` source code — same OpenAI-compatible API, same env vars
- `fiftybox-local/SKILL.md` logic — same phase structure, same env var names
- `qwen-implement-plan` and all Phase 5+ paths — untouched
- The Ollama container `ollama-qwen35` remains on the server (not deleted); `9start`/`9stop` aliases remain functional for manual use

## Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| BF16+FP8 quant VRAM exceeds 24GB | Reduce `--gpu-memory-utilization` to 0.70 or lower `--max-model-len` to 65536 |
| vLLM startup time slower than Ollama | `serve-vllm-qwen35-9b-spec.sh` timeout set to 180s (Ollama was 120s) |
| Ngram speedup lower than expected | Tune `--num-speculative-tokens` (try 3 or 8); or switch to Qwen3-0.5B draft model |
| `fp8` quantization unsupported on sm_86 | Fall back to `--dtype bfloat16` without `--quantization fp8` (weights stay BF16, ~18GB, still fits with reduced kv-cache) |

## Files Changed

| File | Change |
|------|--------|
| `skills/fiftybox-local/scripts/select_remote_model.sh` | `9b` case: alias `9spec-start`, port 8001 |
| `skills/fiftybox-local/scripts/stop_remote_model.sh` | `9b` case: alias `9spec-stop` |
| `skills/fiftybox-local/SKILL.md` | Port reference 11434 → 8001 in Phase 1 comment |
| **Remote server** | New container, new serve script, new zsh aliases |
