#!/usr/bin/env bash
# Sends prompts of increasing complexity to the laya-router model group and
# prints which deployment (tier) each one got routed to.
set -euo pipefail

HOST="${LITELLM_HOST:-http://localhost:4000}"
KEY="${LITELLM_MASTER_KEY:-local-dev-key}"

prompts=(
  "What is 12 + 7?"
  "Write a short haiku about autumn."
  "Explain the tradeoffs between optimistic and pessimistic locking in a database."
  "Design a rate limiter that works correctly across a distributed fleet of API servers, and explain how it handles clock skew between nodes."
)

for prompt in "${prompts[@]}"; do
  echo "=== Prompt: $prompt"
  # The response body's "model" field always echoes back the model group
  # name ("laya-router"), not the deployment that actually answered -- the
  # routed deployment only shows up in the x-litellm-model-name header.
  response=$(curl -s -D /tmp/laya-demo-headers.txt "$HOST/v1/chat/completions" \
    -H "Authorization: Bearer $KEY" \
    -H "Content-Type: application/json" \
    -d "$(jq -n --arg p "$prompt" '{model: "laya-router", messages: [{role: "user", content: $p}]}')")
  routed_model=$(grep -i "^x-litellm-model-name:" /tmp/laya-demo-headers.txt | cut -d' ' -f2 | tr -d '\r')
  echo "routed to: $routed_model"
  echo "$response" | jq '{content: .choices[0].message.content}'
  echo
done
