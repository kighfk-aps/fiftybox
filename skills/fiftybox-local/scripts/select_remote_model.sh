#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat >&2 <<'USAGE'
Usage: select_remote_model.sh [9b|27b|35b|current]

Starts or verifies the remote GPU model on tanpapa@100.121.45.122, waits for
the OpenAI-compatible /v1/models endpoint, then prints shell export statements.

Use with:
  eval "$(~/.claude/skills/fiftybox-local/scripts/select_remote_model.sh 9b)"
USAGE
}

choice="${1:-27b}"
remote="${FIFTYBOX_LOCAL_REMOTE:-tanpapa@100.121.45.122}"
base_url="${LOCAL_MODEL_BASE_URL:-http://100.121.45.122:8000/v1}"
api_key="${LOCAL_MODEL_API_KEY:-token-abc123}"
ready_timeout="${FIFTYBOX_LOCAL_READY_TIMEOUT:-120}"

case "$choice" in
  9|9b|ollama-9b)
    echo "Using Ollama 9B (always-on, no container start)..." >&2
    base_url="http://100.121.45.122:11434/v1"
    ;;
  27|27b|llama|llamacpp)
    echo "Starting 27B llama.cpp remote model as current..." >&2
    ssh -o BatchMode=yes -o ConnectTimeout=8 "$remote" '~/.local/bin/serve-qwen36-27b-128k.sh' >/dev/null
    ;;
  35|35b|vllm)
    echo "Starting 35B vLLM remote model as current..." >&2
    ssh -o BatchMode=yes -o ConnectTimeout=8 "$remote" '~/.local/bin/serve-vllm-current' >/dev/null
    ;;
  current|keep|existing)
    echo "Keeping current remote model; verifying readiness..." >&2
    ;;
  -h|--help|help)
    usage
    exit 0
    ;;
  *)
    echo "Unsupported remote model choice: $choice" >&2
    usage
    exit 2
    ;;
esac

deadline=$((SECONDS + ready_timeout))
model_name=""
model_json=""

while [ "$SECONDS" -lt "$deadline" ]; do
  if model_json="$(
    curl -fsS --max-time 10 "$base_url/models" \
      -H "Authorization: Bearer $api_key" 2>/dev/null
  )"; then
    if model_name="$(
      printf '%s' "$model_json" |
      python3 -c 'import json,sys
data=json.load(sys.stdin)
models=data.get("data") or []
if not models:
    raise SystemExit("no models returned from /v1/models")
print(models[0]["id"])'
    )"; then
      if [ -n "$model_name" ]; then
        break
      fi
    fi
  fi

  echo "Waiting for remote model endpoint at $base_url..." >&2
  sleep 2
done

if [ -z "$model_name" ]; then
  echo "Remote endpoint did not become ready within ${ready_timeout}s" >&2
  ssh -o BatchMode=yes -o ConnectTimeout=8 "$remote" \
    'docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | grep -E "llama|vllm" || true' >&2 || true
  exit 1
fi

cat <<EXPORTS
export LOCAL_MODEL_BASE_URL=$(printf '%q' "$base_url")
export LOCAL_MODEL_API_KEY=$(printf '%q' "$api_key")
export LOCAL_MODEL_NAME=$(printf '%q' "$model_name")
export QWEN_SUMMARY_BASE_URL=$(printf '%q' "$base_url")
export QWEN_SUMMARY_MODEL=$(printf '%q' "$model_name")
export QWEN_SUMMARY_API_KEY=$(printf '%q' "$api_key")
export QWEN_SUMMARY_TIMEOUT=300
export OPENAI_BASE_URL=$(printf '%q' "$base_url")
export OPENAI_API_KEY=$(printf '%q' "$api_key")
EXPORTS

echo "Remote model ready: $model_name at $base_url" >&2
