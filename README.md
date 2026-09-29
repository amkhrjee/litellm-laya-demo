# litellm-laya-demo

Demonstrates the `laya` routing strategy for [LiteLLM](https://github.com/BerriAI/litellm):
a single `model_name` group backed by several deployments of different sizes,
where the [`laya`](https://huggingface.co/convaiinnovations/laya) decision
model scores each incoming prompt's complexity and picks the deployment tier
that matches, instead of you hardcoding which model handles which request.

The `laya` routing strategy is not in upstream LiteLLM yet — it lives on a
feature branch of a fork. This repo is just the config + instructions to run
that branch locally and see it work end-to-end against real Ollama models.

## How it works

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

## Prerequisites

- Python 3.11+ and [`uv`](https://docs.astral.sh/uv/)
- [Ollama](https://ollama.com) running somewhere reachable (local or remote)
- ~20GB free disk for the four demo models pulled below (drop to fewer/smaller
  models if that's too much — see "Using different models")

## 1. Get the litellm branch with laya routing

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

## Verified

Ran this end-to-end against the `feature/add-laya-routing` branch and a real
Ollama server (swapping in models that were actually pulled there —
`deepseek-r1:1.5b`/`qwen3.5:4b`/`qwen3.6:27b`/`gpt-oss:120b` as
tiny/small/medium/large — since this repo's default tags weren't available on
that particular server). The proxy started cleanly, `laya` loaded and scored
requests, and routing genuinely varied by prompt: a distributed-rate-limiter
design question landed on the medium tier, a simple arithmetic question landed
on the small tier. Neither matched the "obvious" human tier for that prompt —
that's laya's own calibration on the default tier descriptions, not a routing
bug (the mechanism correctly sent each request to whichever tier laya scored
it as). If you want tighter alignment with your own intuition for what counts
as "tiny" vs "large", tune the tier `description` text via
`routing_strategy_args.tiers` in `config.yaml`.

## Using different models

Swap the `model` under `litellm_params` for any four deployments you want —
they don't have to be Ollama, and they don't have to be exactly four (any
number ≥ 2 works, as long as `complexity_tier` values are unique and match
whatever tier names you configure). If you customize the tier names, add the
matching `routing_strategy_args.tiers` block in `config.yaml` so laya's
scoring rubric lines up with your deployments.

## Troubleshooting

- **`ValidationError` mentioning `tier`**: LiteLLM's `ModelInfo` already has a
  `tier` field reserved for budget routing (`"free"` / `"paid"`). This demo
  uses `complexity_tier` instead — don't rename it back to `tier`.
- **Proxy takes a while on the first request**: that's `laya` loading its
  checkpoint from the HF cache on first use, not a hang.
- **`laya` disappears after restarting via `uv run`**: see the warning in
  step 3 — use `.venv/bin/litellm` directly instead.
