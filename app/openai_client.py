from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class OpenAIConfig:
    api_key: str
    base_url: str = "https://api.openai.com/v1"


def _cfg_from_env() -> OpenAIConfig:
    key = os.getenv("OPENAI_API_KEY") or ""
    if not key.strip():
        raise RuntimeError("OPENAI_API_KEY is required")
    base = (os.getenv("OPENAI_API_BASE") or "https://api.openai.com/v1").strip().rstrip("/")
    return OpenAIConfig(api_key=key.strip(), base_url=base)


def _post_json(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    cfg = _cfg_from_env()
    url = f"{cfg.base_url}{path}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Authorization", f"Bearer {cfg.api_key}")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=60) as resp:  # nosec - outbound to OpenAI only
        raw = resp.read().decode("utf-8")
        return json.loads(raw)


def create_chat_json(*, model: str, messages: list[dict[str, str]], response_format: dict[str, Any]) -> dict[str, Any]:
    return _post_json(
        "/chat/completions",
        {
            "model": model,
            "messages": messages,
            "response_format": response_format,
            "temperature": 0.2,
        },
    )


def embed_texts(*, model: str, inputs: list[str]) -> list[list[float]]:
    res = _post_json(
        "/embeddings",
        {
            "model": model,
            "input": inputs,
        },
    )
    data = res.get("data")
    if not isinstance(data, list):
        raise RuntimeError("openai_embeddings_invalid")
    out: list[list[float]] = []
    for row in data:
        emb = row.get("embedding") if isinstance(row, dict) else None
        if not isinstance(emb, list):
            raise RuntimeError("openai_embeddings_invalid")
        out.append([float(x) for x in emb])
    return out

