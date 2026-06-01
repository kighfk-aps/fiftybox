#!/usr/bin/env bash
# Normalized adapter: cursor.sh "<prompt>" "<task>" "<model>"
# Cursor CLI does not support --message; uses positional input via stdin pipe.
set -euo pipefail
PROMPT="$1"
TASK="$2"
MODEL="${3:-}"
if [[ -n "$MODEL" ]]; then
    printf '%s\n%s' "$PROMPT" "$TASK" | cursor chat --model "$MODEL" --stdin
else
    printf '%s\n%s' "$PROMPT" "$TASK" | cursor chat --stdin
fi
