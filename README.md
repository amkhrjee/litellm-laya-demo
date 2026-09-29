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

If a laya-enabled proxy is already running (e.g. reachable at the web UI's
default URL), skip straight to step 8 — steps 1-7 are only for standing one
up from scratch.

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
ollama pull deepseek-r1:1.5b   # tiny
ollama pull qwen3.5:4b         # small
ollama pull qwen3.6:27b        # medium
ollama pull gpt-oss:120b       # large
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

## 8. Run the web UI

A small page (`server/static/index.html`, modeled on `router-test`) lets you
send prompts from the browser and see the routing decision without curl —
and see it immediately, before the LLM finishes generating.

It's backed by a small FastAPI app (`server/app.py`) rather than a plain
static file server, for a reason: litellm's CORS config only exposes a small
fixed allowlist of response headers to cross-origin browser fetches
(`LITELLM_UI_ALLOW_HEADERS` in `litellm/constants.py`), and
`x-litellm-model-name` — the header that reveals which deployment actually
answered — isn't on it. A direct browser→proxy fetch silently can't see it.
The backend calls the proxy server-to-server instead (no CORS involved there),
reads the header off the real HTTP response, and relays it to the browser
over SSE. Combined with `stream: true` on the upstream request, the routing
decision is known and forwarded the moment litellm picks a deployment —
independently measured at ~13ms — while the generated tokens stream in
afterward, which took 188s for a large/complex prompt in testing. The decision
never waits on generation.

Install and run:

```bash
cd /path/to/litellm-laya-demo
uv sync
./serve.sh
```

This runs the app on `0.0.0.0:1729`. Open `http://localhost:1729` (or
`http://<host>:1729` from another machine), fill in the proxy URL/API key
(defaults to `http://10.129.6.181:4000` / `local-dev-key`), type a prompt, and
hit "Send request." The routing decision (tier, routed model, raw
`x-litellm-*` headers) appears right away; the response streams in below it.

The tier label shown isn't hand-maintained in the frontend: the backend reads
`config.yaml` itself at startup to build the model→tier lookup (litellm
doesn't expose `complexity_tier` as a header, only the model name), so
changing which models `config.yaml` uses just works without touching any UI
code.

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

Also ran the web UI's backend directly (bypassing the browser) against the
same proxy: the SSE `decision` event for a simple prompt arrived and the whole
exchange (routing + a short generation) completed in ~22s; for the
distributed-rate-limiter prompt, the decision event arrived in 13ms while
total generation took 188s, confirming the decision truly isn't gated on
generation.

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
