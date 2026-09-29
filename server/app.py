"""Backend for the laya routing demo UI.

The browser cannot read litellm's `x-litellm-*` routing headers directly:
they aren't on litellm's CORS `expose_headers` allowlist (litellm/constants.py
LITELLM_UI_ALLOW_HEADERS), so a cross-origin fetch from the static page hides
them even though curl or any other server-to-server client sees them fine.

This backend sits between the browser and the real LiteLLM proxy so the
header read happens server-to-server (no CORS involved), then relays the
routing decision to the browser over SSE the moment it's known -- which, with
a streaming upstream request, is as soon as litellm picks a deployment and
starts the response, well before generation finishes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import AsyncIterator

import httpx
import yaml
from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

STATIC_DIR = Path(__file__).parent / "static"
CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"

app = FastAPI()


def _load_tier_by_model() -> dict[str, str]:
    """Maps each laya-router deployment's litellm model string to its
    complexity_tier, read straight from config.yaml -- the single place that
    mapping is actually defined -- instead of duplicating it by hand.
    """
    config = yaml.safe_load(CONFIG_PATH.read_text())
    return {
        entry["litellm_params"]["model"]: entry["model_info"]["complexity_tier"]
        for entry in config["model_list"]
        if entry.get("model_name") == "laya-router"
    }


TIER_BY_MODEL = _load_tier_by_model()


class GenerateRequest(BaseModel):
    proxy_url: str
    api_key: str
    prompt: str


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def _stream(req: GenerateRequest) -> AsyncIterator[str]:
    base_url = req.proxy_url.rstrip("/")
    payload = {
        "model": "laya-router",
        "messages": [{"role": "user", "content": req.prompt}],
        "stream": True,
    }
    headers = {"Authorization": f"Bearer {req.api_key}"}

    async with httpx.AsyncClient(timeout=None) as client:
        try:
            async with client.stream(
                "POST", f"{base_url}/v1/chat/completions", json=payload, headers=headers
            ) as upstream:
                routing_headers = {k: v for k, v in upstream.headers.items() if k.lower().startswith("x-litellm-")}
                routed_model = routing_headers.get("x-litellm-model-name", "not reported")
                yield _sse(
                    "decision",
                    {
                        "status": upstream.status_code,
                        "routed_model": routed_model,
                        "tier": TIER_BY_MODEL.get(routed_model, "unknown"),
                        "headers": routing_headers,
                    },
                )

                if upstream.status_code != 200:
                    body = await upstream.aread()
                    yield _sse("error", {"body": body.decode(errors="replace")})
                    return

                async for line in upstream.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[len("data:") :].strip()
                    if data == "[DONE]":
                        break
                    try:
                        parsed = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    delta = parsed.get("choices", [{}])[0].get("delta", {}).get("content")
                    if delta:
                        yield _sse("chunk", {"content": delta})
        except httpx.HTTPError as exc:
            yield _sse("error", {"body": str(exc)})
            return

    yield _sse("done", {})


@app.post("/api/generate")
async def generate(req: GenerateRequest):
    return StreamingResponse(_stream(req), media_type="text/event-stream")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")
