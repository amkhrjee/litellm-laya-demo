# litellm-laya-demo

## Internally how it works...

- Every deployment in the `laya-router` model group is tagged with
  `model_info.complexity_tier` (`tiny` / `small` / `medium` / `large` by
  default).
- On each request, the strategy pulls the latest user message, asks `laya` to
  score it against a "how complex is this to answer well?" rubric, and maps
  the score to the nearest tier.
- It then picks the deployment whose `complexity_tier` matches. If no
  deployment carries that exact tier, it falls back to the first healthy
  deployment and logs a warning.
- Tiers and their descriptions (the text `laya` is actually scored against)
  are configurable via `router_settings.routing_strategy_args.tiers` — see
  the commented-out block in `config.yaml`.

(Setup guide written with LLM, but checked by me)

## 1. How to setup

```bash
git clone https://github.com/amkhrjee/litellm.git
cd litellm
git checkout feature/add-laya-routing
```

## 2. Install litellm with proxy extras

```bash
uv sync --extra proxy
```

## 3. Install laya

`laya` and its dependencies (including `torch`) aren't declared in litellm's
own `pyproject.toml`, so install them directly into the venv `uv sync` just
created:

```bash
uv pip install laya
```

Important: from here on, **don't** run the proxy with `uv run litellm ...`.
`uv run` re-syncs the environment against litellm's lockfile first, which
will happily remove `laya`/`torch` again since they aren't declared
dependencies. Invoke the venv's binary directly instead (step 6).

## 4. Pull the demo models in Ollama

```bash
ollama pull llama3.2:1b     # tiny
ollama pull qwen2.5:3b      # small
ollama pull qwen2.5:14b     # medium
ollama pull qwen2.5:32b     # large
```

## 5. Point the config at your Ollama server


```bash
export OLLAMA_API_BASE="http://localhost:11434"   # or wherever Ollama is running
export LITELLM_MASTER_KEY="local-dev-key"
```

## 6. Run the proxy

From inside the `litellm` checkout, pointing at this repo's config:

```bash
.venv/bin/litellm --config /path/to/litellm-laya-demo/config.yaml --port 4000
```

The first request will lazily load the `laya` model (one-time cost); after
that, classification is fast.

## 7. Try it

```bash
cd /path/to/litellm-laya-demo
./scripts/test_routing.sh
```

This sends four prompts of increasing complexity and prints which deployment
each one got routed to.

Note: the response body's `model` field is **not** useful here — it always
echoes back the model group name (`"laya-router"`), not the deployment that
actually answered. The routing decision shows up in the `x-litellm-model-name`
response header instead, which is what the script checks.

Or by hand:

```bash
curl -D - http://localhost:4000/v1/chat/completions \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model": "laya-router", "messages": [{"role": "user", "content": "What is 12 + 7?"}]}' \
  | grep -i x-litellm-model-name
```
