"""LM Studio OpenAI-compatible client for Civ6Ai.

Lessons ported from Civ5 sidecar:
- reasoning is on|off only; never send reasoning_effort=on (LM Studio rejects it)
- split text + image into multimodal content parts (empty completions otherwise)
- long timeouts (~600s) with retries for sequential seats
- clear errors when the model is unloaded (HTTP 400)
- optional shared-model lock so seats queue instead of stampeding one server
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Callable

from sidecar import civ6_config
from sidecar import pipeline_v2 as pipeline
from sidecar.civ6_config import Civ6AiLocalConfig, load_local_config, normalize_reasoning

OpenFn = Callable[..., Any]

_SHARED_LOCK = threading.Lock()
_MODEL_UNLOADED_MARKERS = (
    "model unloaded",
    "no models loaded",
    "model is not loaded",
    "not currently loaded",
    "failed to load model",
    "could not find model",
)


def lmstudio_chat_reasoning_fields(model: str | None, reasoning: str) -> dict[str, Any]:
    """Build LM Studio chat.completions reasoning controls.

    Qwen / vision stacks: top-level ``reasoning`` = ``on``|``off``.
    Never emit ``reasoning_effort=on`` (rejected by LM Studio).
    gpt-oss: nested ``reasoning: {effort: ...}``.
    Non-thinking models: force off.
    """
    model_l = (model or "").strip().lower()
    level = normalize_reasoning(reasoning)
    if "gpt-oss" in model_l:
        if level == "off":
            return {"reasoning": "off"}
        return {"reasoning": {"effort": "low"}}
    thinking = any(tok in model_l for tok in ("qwen", "deepseek", "r1", "reasoning", "nemotron", "vl"))
    if not thinking:
        return {"reasoning": "off"}
    return {"reasoning": "on" if level == "on" else "off"}


def build_chat_user_content(
    wire_text: str,
    image_data_url: str | list[dict[str, str]] | list[str] | None,
    *,
    vision: bool,
) -> str | list[dict[str, Any]]:
    """Split text + images into OpenAI multimodal content parts when vision is on."""
    attachments = pipeline.normalize_image_attachments(image_data_url) if vision else []
    if not attachments:
        return wire_text
    content: list[dict[str, Any]] = [{"type": "text", "text": wire_text}]
    for attachment in attachments:
        content.append({
            "type": "image_url",
            "image_url": {
                "url": attachment["data_url"],
                "detail": attachment.get("detail", "low"),
            },
        })
    return content


def build_chat_completions_body(
    *,
    snapshot: dict[str, Any],
    cfg: Civ6AiLocalConfig,
    image_data_url: str | list[dict[str, str]] | list[str] | None = None,
    system_prompt: str | None = None,
    wire_text: str | None = None,
) -> dict[str, Any]:
    """Build the JSON body for POST /v1/chat/completions (mockable in unit tests)."""
    wire = wire_text if isinstance(wire_text, str) else pipeline.build_model_wire_text(snapshot)
    system = system_prompt if isinstance(system_prompt, str) else pipeline._model_instructions(snapshot)
    user_content = build_chat_user_content(wire, image_data_url, vision=bool(cfg.vision))
    body: dict[str, Any] = {
        "model": cfg.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
        "max_tokens": 4096,
    }
    body.update(lmstudio_chat_reasoning_fields(cfg.model, cfg.reasoning))
    # Guard: never allow a bare reasoning_effort=on through.
    if body.get("reasoning_effort") in {"on", "off", "true", "false"}:
        body.pop("reasoning_effort", None)
    return body


def _is_model_unloaded_error(status: int, detail: str) -> bool:
    if status != 400 and status != 404:
        return False
    hay = (detail or "").lower()
    return any(marker in hay for marker in _MODEL_UNLOADED_MARKERS)


def _chat_message_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise pipeline.BoundaryError("api_output", "LM Studio returned no choices")
    choice0 = choices[0] if isinstance(choices[0], dict) else {}
    message = choice0.get("message") if isinstance(choice0, dict) else {}
    if not isinstance(message, dict):
        raise pipeline.BoundaryError("api_output", "LM Studio choice has no message")
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content
    if isinstance(content, list):
        parts = [
            item.get("text", "")
            for item in content
            if isinstance(item, dict) and isinstance(item.get("text"), str)
        ]
        joined = "\n".join(p for p in parts if p.strip())
        if joined.strip():
            return joined
    for key in ("reasoning_content", "reasoning", "thinking"):
        alt = message.get(key)
        if isinstance(alt, str) and alt.strip():
            return alt
    keys = ",".join(sorted(str(k) for k in message.keys()))
    finish = choice0.get("finish_reason")
    raise pipeline.BoundaryError(
        "api_output",
        f"LM Studio returned empty completion (keys={keys} finish_reason={finish})",
    )


def list_loaded_models(
    cfg: Civ6AiLocalConfig | None = None,
    *,
    opener: OpenFn | None = None,
    timeout_seconds: float = 10.0,
) -> list[dict[str, Any]]:
    cfg = cfg or load_local_config()
    url = cfg.models_url
    request = urllib.request.Request(url, method="GET", headers={"Authorization": f"Bearer {cfg.api_key}"})
    open_request = opener or urllib.request.urlopen
    try:
        with open_request(request, timeout=timeout_seconds) as response:
            raw = response.read(2_000_000)
            payload = json.loads(raw.decode("utf-8"))
    except Exception as error:
        raise pipeline.BoundaryError("transport", f"LM Studio /models failed: {error}") from error
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return []
    return [row for row in data if isinstance(row, dict)]


def call_lmstudio_chat(
    snapshot: dict[str, Any],
    *,
    cfg: Civ6AiLocalConfig | None = None,
    image_data_url: str | list[dict[str, str]] | list[str] | None = None,
    opener: OpenFn | None = None,
    wire_text: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """POST chat.completions to LM Studio with retries and shared-model queueing."""
    cfg = cfg or load_local_config()
    body = build_chat_completions_body(
        snapshot=snapshot,
        cfg=cfg,
        image_data_url=image_data_url,
        wire_text=wire_text,
    )
    url = cfg.chat_completions_url
    request = urllib.request.Request(
        url,
        data=pipeline.canonical_json(body).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {cfg.api_key}",
            "Content-Type": "application/json",
        },
    )
    open_request = opener or urllib.request.urlopen
    started = time.monotonic()
    lock = _SHARED_LOCK if cfg.queue_shared_model else None

    def _once() -> tuple[dict[str, Any], dict[str, Any]]:
        last_error: Exception | None = None
        for attempt in range(max(1, cfg.max_retries)):
            try:
                with open_request(request, timeout=cfg.timeout_seconds) as response:
                    raw = response.read(pipeline.MAX_RESPONSE_BYTES + 1)
                    if len(raw) > pipeline.MAX_RESPONSE_BYTES:
                        raise pipeline.BoundaryError("oversized_output", "LM Studio body exceeds limit")
                    payload = json.loads(raw.decode("utf-8"))
                    text = _chat_message_text(payload)
                    result = pipeline.parse_model_text(text)
                    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
                    metadata = {
                        "status": getattr(response, "status", 200),
                        "provider": "lmstudio",
                        "model": payload.get("model") or cfg.model,
                        "response_id": payload.get("id"),
                        "usage": usage,
                        "latency_ms": int((time.monotonic() - started) * 1000),
                        "vision_enabled": bool(cfg.vision and image_data_url),
                        "reasoning": body.get("reasoning"),
                        "endpoint": cfg.endpoint,
                        "attempts": attempt + 1,
                    }
                    return result, metadata
            except urllib.error.HTTPError as error:
                detail = ""
                try:
                    detail = error.read(4000).decode("utf-8", errors="replace")
                except Exception:
                    pass
                if _is_model_unloaded_error(error.code, detail):
                    raise pipeline.BoundaryError(
                        "model_unloaded",
                        "LM Studio has no model loaded (HTTP "
                        f"{error.code}). Load a Qwen vision model in LM Studio, "
                        f"then retry. Detail: {detail[:300]}",
                    ) from error
                if error.code in getattr(pipeline, "TRANSIENT_HTTP_CODES", {408, 429, 500, 502, 503, 504}):
                    last_error = error
                    time.sleep(2 * (attempt + 1))
                    continue
                raise pipeline.BoundaryError(
                    pipeline._http_error_category(error.code)
                    if hasattr(pipeline, "_http_error_category")
                    else "api_error",
                    f"LM Studio HTTP {error.code}: {detail[:500]}",
                ) from error
            except (urllib.error.URLError, TimeoutError, ConnectionResetError, OSError) as error:
                last_error = error
                if attempt >= cfg.max_retries - 1:
                    raise pipeline.BoundaryError(
                        "transport",
                        f"LM Studio transport failed after {cfg.max_retries} attempts: {error}",
                    ) from error
                time.sleep(2 * (attempt + 1))
        raise pipeline.BoundaryError(
            "transport",
            f"LM Studio transport failed: {last_error}",
        )

    if lock is None:
        return _once()
    with lock:
        return _once()
