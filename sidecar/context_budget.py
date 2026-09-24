"""Dynamic token-aware context budgeting for Civ5Ai prompts.

Detects the active model's context window (LM Studio or OpenRouter), reserves
headroom for reasoning/output, and applies a graceful degradation ladder so
estimated prompt tokens + reserve stay within the limit.

Reserve policy (documented):
  Always leave room for the required reply structure:
    THINKING (reasoning_content): 4 paragraphs
      1) map.read / strategicmap.read / tacticalmap.read (one paragraph per map)
      2) free thinking / thought.situation (one paragraph)
      3) thought.strategy (victory path + this turn's command plan; one paragraph)
    CONTENT: 1 block of numbered commands only
  Default estimate: CIV5AI_THINKING_PARAGRAPH_TOKENS (default 900) × 4
                  + CIV5AI_CONTENT_BLOCK_TOKENS (default 600)
                  = ~4200 tokens, with a floor of MIN_RESERVE_TOKENS (4096).
  Absolute override: CIV5AI_CONTEXT_RESERVE_TOKENS wins when set.
  Optional ratio floor: max(paragraph_reserve, ratio*context) when
  CIV5AI_CONTEXT_RESERVE_RATIO is set (default off / 0 — paragraph-based only).

Degradation ladder (maps LAST — David 2026-09-06):
  1. foreign_units truncated (position/type only)
  2. story trimmed (keep >= 3 entries)
  3. own_units truncated too (position + type/id)
  4. chat log capped to 5 messages
  5. cities truncated (name + currently building for self)
  6. map images: omit tactical, then 768→512 on remaining
"""
from __future__ import annotations

import json
import logging
import math
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable
from urllib import error as urllib_error
from urllib import request as urllib_request

LOG = logging.getLogger("civ5ai.context_budget")

DEFAULT_CONTEXT_FALLBACK = 32768
DEFAULT_RESERVE_RATIO = 0.0  # paragraph-based by default; set env ratio to add a floor
MIN_RESERVE_TOKENS = 4096
DEFAULT_THINKING_PARAGRAPH_TOKENS = 900  # generous per thinking paragraph
DEFAULT_CONTENT_BLOCK_TOKENS = 600  # numbered commands block
THINKING_PARAGRAPH_COUNT = 4
CONTENT_BLOCK_COUNT = 1
IMAGE_SIZE_LADDER = (768, 512)
STORY_MIN_ENTRIES = 3
CHAT_BUDGET_MAX_MESSAGES = 5
CHARS_PER_TOKEN = 4.0
VISION_PATCH_PX = 28
PROMPT_ESTIMATE_SAFETY = 1.15  # overestimate to absorb tokenizer/vision variance
VISION_TOKEN_SAFETY = 1.35  # VLM image tokens often exceed raw patch-grid

# Cache: (provider, model) -> (limit, source, fetched_monotonic)
_CONTEXT_CACHE: dict[tuple[str, str], tuple[int, str, float]] = {}
_CONTEXT_CACHE_TTL_SECONDS = 300.0


@dataclass
class ContextLimitInfo:
    provider: str
    model: str
    context_limit: int
    source: str  # env | lmstudio | openrouter | fallback
    reserve_tokens: int

    @property
    def prompt_token_budget(self) -> int:
        return max(1024, self.context_limit - self.reserve_tokens)


@dataclass
class BudgetPlan:
    """Chosen truncation / image settings for one seat turn."""
    foreign_units: str = "full"  # full | truncated
    own_units: str = "full"  # full | truncated
    story: str = "full"  # full | trimmed
    story_min_entries: int = STORY_MIN_ENTRIES
    chat_max_messages: int | None = None  # None = default window
    cities: str = "full"  # full | truncated
    overview_image_size: int = 768
    tactical_image_size: int = 1024  # 0 = omit tactical
    focus_image_size: int = 0
    omit_tactical: bool = False
    omit_focus: bool = True
    steps_applied: list[str] = field(default_factory=list)

    def as_wire_options(self) -> dict[str, Any]:
        omit_focus = self.omit_focus or self.omit_tactical or self.focus_image_size <= 0
        return {
            "foreign_units": self.foreign_units,
            "own_units": self.own_units,
            "story": self.story,
            "story_min_entries": self.story_min_entries,
            "chat_max_messages": self.chat_max_messages,
            "cities": self.cities,
            "overview_image_size": self.overview_image_size,
            "tactical_image_size": 0 if self.omit_tactical else self.tactical_image_size,
            "focus_image_size": 0 if omit_focus else self.focus_image_size,
            "omit_tactical": self.omit_tactical,
            "omit_focus": omit_focus,
            "steps_applied": list(self.steps_applied),
        }


def _env_first(*names: str, default: str = "") -> str:
    for name in names:
        raw = os.environ.get(name, "").strip()
        if raw:
            return raw
    return default


def _env_int(*names: str, default: int | None = None) -> int | None:
    raw = _env_first(*names)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(*names: str, default: float | None = None) -> float | None:
    raw = _env_first(*names)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def model_provider() -> str:
    raw = _env_first("CIV6AI_MODEL_PROVIDER", "CIV4AI_MODEL_PROVIDER", default="gemini").lower()
    return raw


def active_model_name(provider: str | None = None) -> str:
    active = (provider or model_provider()).strip().lower()
    if active == "lmstudio":
        return _env_first("LMSTUDIO_MODEL", "OPENAI_MODEL")
    if active == "openrouter":
        return _env_first("OPENAI_MODEL", "OPENROUTER_MODEL", default="qwen/qwen3.7-flash")
    return _env_first("OPENAI_MODEL", "OPENROUTER_MODEL", "LMSTUDIO_MODEL")


def lmstudio_base_url() -> str:
    return _env_first("LMSTUDIO_BASE_URL", default="http://127.0.0.1:1234/v1").rstrip("/")


def openrouter_base_url() -> str:
    return _env_first("OPENAI_BASE_URL", default="https://openrouter.ai/api/v1").rstrip("/")


def openrouter_api_key() -> str:
    return _env_first("OPENROUTER_API_KEY", "OPENAI_API_KEY")


def paragraph_output_reserve_tokens() -> int:
    """Tokens reserved for 4 thinking paragraphs + 1 content commands block."""
    para = _env_int(
        "CIV5AI_THINKING_PARAGRAPH_TOKENS",
        "CIV4AI_THINKING_PARAGRAPH_TOKENS",
        default=DEFAULT_THINKING_PARAGRAPH_TOKENS,
    ) or DEFAULT_THINKING_PARAGRAPH_TOKENS
    content = _env_int(
        "CIV5AI_CONTENT_BLOCK_TOKENS",
        "CIV4AI_CONTENT_BLOCK_TOKENS",
        default=DEFAULT_CONTENT_BLOCK_TOKENS,
    ) or DEFAULT_CONTENT_BLOCK_TOKENS
    para = max(200, min(4000, int(para)))
    content = max(150, min(4000, int(content)))
    return THINKING_PARAGRAPH_COUNT * para + CONTENT_BLOCK_COUNT * content


def compute_reserve_tokens(context_limit: int) -> int:
    """Reserve for 4 thinking paragraphs + 1 content block; absolute env wins.

    Shrink ladder must fire before this reserve is eaten. Prompt budget is
    context_limit - reserve.
    """
    absolute = _env_int("CIV5AI_CONTEXT_RESERVE_TOKENS", "CIV4AI_CONTEXT_RESERVE_TOKENS")
    if absolute is not None and absolute >= 0:
        cap = max(0, int(context_limit) - 1024)
        return min(cap, absolute) if context_limit > 1024 else absolute

    paragraph_reserve = paragraph_output_reserve_tokens()
    reserve = max(MIN_RESERVE_TOKENS, paragraph_reserve)

    # Optional ratio floor (off by default). When set > 0, take max(paragraph, ratio*limit).
    ratio = _env_float("CIV5AI_CONTEXT_RESERVE_RATIO", "CIV4AI_CONTEXT_RESERVE_RATIO", default=DEFAULT_RESERVE_RATIO)
    if ratio is not None and float(ratio) > 0:
        ratio = max(0.05, min(0.50, float(ratio)))
        reserve = max(reserve, int(round(int(context_limit) * ratio)))

    cap = max(0, int(context_limit) - 1024)
    return min(cap, reserve) if context_limit > 1024 else min(int(context_limit), reserve)


def estimate_text_tokens(text: str) -> int:
    """Token-aware estimate: tiktoken if available, else chars/4."""
    if not text:
        return 0
    try:
        import tiktoken  # type: ignore

        try:
            enc = tiktoken.get_encoding("cl100k_base")
        except Exception:
            enc = tiktoken.get_encoding("o200k_base")
        return max(1, len(enc.encode(text)))
    except Exception:
        return max(1, int(math.ceil(len(text) / CHARS_PER_TOKEN)))


def estimate_vision_tokens(width: int, height: int, *, patch: int = VISION_PATCH_PX) -> int:
    """Qwen-style patch grid estimate (conservative for budgeting).

    Inflates by VISION_TOKEN_SAFETY because LM Studio/Qwen VLM token counts for
    letterboxed strategic maps often exceed the raw patch-grid formula.
    """
    w = max(1, int(width))
    h = max(1, int(height))
    p = max(8, int(patch))
    raw = max(64, math.ceil(w / p) * math.ceil(h / p))
    return max(64, int(math.ceil(raw * VISION_TOKEN_SAFETY)))


def estimate_prompt_tokens(
    text: str,
    *,
    image_sizes: list[int] | None = None,
    safety: float = PROMPT_ESTIMATE_SAFETY,
) -> int:
    tokens = estimate_text_tokens(text)
    for size in image_sizes or []:
        if size and size > 0:
            tokens += estimate_vision_tokens(size, size)
    return max(1, int(math.ceil(tokens * safety)))


def _http_get_json(url: str, *, headers: dict[str, str] | None = None, timeout: float = 8.0) -> Any:
    req = urllib_request.Request(url, method="GET", headers=headers or {})
    with urllib_request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read(2_000_000)
    return json.loads(raw.decode("utf-8"))


def _pick_context_from_lmstudio_model(entry: dict[str, Any]) -> int | None:
    for key in (
        "loaded_context_length",
        "max_context_length",
        "context_length",
        "max_context_window",
        "n_ctx",
    ):
        value = entry.get(key)
        if isinstance(value, (int, float)) and int(value) > 0:
            return int(value)
    meta = entry.get("meta") if isinstance(entry.get("meta"), dict) else {}
    for key in ("loaded_context_length", "max_context_length", "context_length", "n_ctx"):
        value = meta.get(key)
        if isinstance(value, (int, float)) and int(value) > 0:
            return int(value)
    extras = entry.get("extras") if isinstance(entry.get("extras"), dict) else {}
    for key in ("loaded_context_length", "context_length"):
        value = extras.get(key)
        if isinstance(value, (int, float)) and int(value) > 0:
            return int(value)
    return None


def _lmstudio_api_root(base_url: str | None = None) -> str:
    """Strip a trailing /v1 so we can hit LM Studio native /api/v0 endpoints."""
    root = (base_url or lmstudio_base_url()).rstrip("/")
    if root.endswith("/v1"):
        root = root[:-3]
    return root.rstrip("/") or "http://127.0.0.1:1234"


def query_lmstudio_context_length(
    model: str | None = None,
    *,
    base_url: str | None = None,
    opener: Callable[..., Any] | None = None,
) -> tuple[int | None, str]:
    """Query LM Studio for loaded_context_length.

    Prefers native GET /api/v0/models (exposes loaded_context_length), then falls
    back to OpenAI-compatible GET /v1/models.
    """
    target = (model or active_model_name("lmstudio")).strip()
    api_root = _lmstudio_api_root(base_url)
    openai_root = (base_url or lmstudio_base_url()).rstrip("/")
    urls = [api_root + "/api/v0/models", openai_root + "/models"]
    payload = None
    last_err = "lmstudio_unreachable"
    for url in urls:
        try:
            if opener is None:
                payload = _http_get_json(url, timeout=6.0)
            else:
                req = urllib_request.Request(url, method="GET")
                with opener(req, timeout=6.0) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
            break
        except Exception as exc:
            last_err = f"lmstudio_error:{type(exc).__name__}"
            payload = None
    if payload is None:
        return None, last_err

    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        data = payload if isinstance(payload, list) else []
    preferred: list[dict[str, Any]] = []
    others: list[dict[str, Any]] = []
    target_l = target.lower()
    for entry in data:
        if not isinstance(entry, dict):
            continue
        mid = str(entry.get("id") or entry.get("model") or "").strip()
        if target_l and mid.lower() == target_l:
            preferred.insert(0, entry)
        elif target_l and target_l in mid.lower():
            preferred.append(entry)
        else:
            others.append(entry)
    ordered = preferred + others
    # Prefer an explicitly loaded instance when the native API tags state.
    loaded = [e for e in ordered if str(e.get("state", "")).lower() == "loaded"]
    for entry in loaded + ordered:
        found = _pick_context_from_lmstudio_model(entry)
        if found:
            return found, "lmstudio"
    return None, "lmstudio_missing_field"


def _pick_context_from_openrouter_model(entry: dict[str, Any]) -> int | None:
    for key in ("context_length", "max_context_length", "context_window"):
        value = entry.get(key)
        if isinstance(value, (int, float)) and int(value) > 0:
            return int(value)
    top = entry.get("top_provider") if isinstance(entry.get("top_provider"), dict) else {}
    for key in ("context_length", "max_completion_tokens"):
        # max_completion_tokens alone is NOT full context; skip it for limit
        if key == "max_completion_tokens":
            continue
        value = top.get(key)
        if isinstance(value, (int, float)) and int(value) > 0:
            return int(value)
    arch = entry.get("architecture") if isinstance(entry.get("architecture"), dict) else {}
    value = arch.get("context_length")
    if isinstance(value, (int, float)) and int(value) > 0:
        return int(value)
    return None


def query_openrouter_context_length(
    model: str | None = None,
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    opener: Callable[..., Any] | None = None,
) -> tuple[int | None, str]:
    """Query OpenRouter /models for context_length / top_provider.context_length."""
    target = (model or active_model_name("openrouter")).strip()
    root = (base_url or openrouter_base_url()).rstrip("/")
    # OpenRouter models list is under /api/v1/models or /models on the openai-compat base.
    url = root + "/models"
    headers: dict[str, str] = {"Accept": "application/json"}
    key = (api_key if api_key is not None else openrouter_api_key()).strip()
    if key:
        headers["Authorization"] = "Bearer " + key
    try:
        if opener is None:
            payload = _http_get_json(url, headers=headers, timeout=12.0)
        else:
            req = urllib_request.Request(url, method="GET", headers=headers)
            with opener(req, timeout=12.0) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        return None, f"openrouter_error:{type(exc).__name__}"

    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return None, "openrouter_bad_payload"
    target_l = target.lower()
    # Prefer exact id match, then suffix match (openrouter sometimes omits org prefix).
    candidates: list[dict[str, Any]] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        mid = str(entry.get("id") or "").strip().lower()
        if not mid:
            continue
        if mid == target_l:
            candidates.insert(0, entry)
        elif target_l and (mid.endswith("/" + target_l) or target_l.endswith("/" + mid) or mid.endswith(target_l)):
            candidates.append(entry)
    for entry in candidates:
        found = _pick_context_from_openrouter_model(entry)
        if found:
            return found, "openrouter"
    # Last resort: scan all for a unique substring hit
    if target_l:
        for entry in data:
            if not isinstance(entry, dict):
                continue
            mid = str(entry.get("id") or "").lower()
            if target_l in mid:
                found = _pick_context_from_openrouter_model(entry)
                if found:
                    return found, "openrouter"
    return None, "openrouter_model_not_found"


def resolve_model_context_limit(
    *,
    provider: str | None = None,
    model: str | None = None,
    use_cache: bool = True,
    opener: Callable[..., Any] | None = None,
) -> ContextLimitInfo:
    """Resolve context limit: env override > provider API > safe fallback."""
    active = (provider or model_provider()).strip().lower()
    resolved_model = (model or active_model_name(active)).strip()

    env_limit = _env_int(
        "CIV5AI_MODEL_CONTEXT",
        "CIV4AI_MODEL_CONTEXT",
        "CIV5AI_CONTEXT_LIMIT",
        "CIV4AI_CONTEXT_LIMIT",
    )
    if env_limit is not None and env_limit >= 2048:
        reserve = compute_reserve_tokens(env_limit)
        return ContextLimitInfo(active, resolved_model, env_limit, "env", reserve)

    cache_key = (active, resolved_model.lower())
    now = time.monotonic()
    if use_cache and cache_key in _CONTEXT_CACHE:
        limit, source, fetched = _CONTEXT_CACHE[cache_key]
        if now - fetched < _CONTEXT_CACHE_TTL_SECONDS:
            return ContextLimitInfo(active, resolved_model, limit, source + "+cache", compute_reserve_tokens(limit))

    limit: int | None = None
    source = "fallback"
    if active == "lmstudio":
        limit, source = query_lmstudio_context_length(resolved_model, opener=opener)
    elif active == "openrouter":
        limit, source = query_openrouter_context_length(resolved_model, opener=opener)
    else:
        # Still try OpenRouter metadata if model id looks like org/model and key exists
        if "/" in resolved_model and openrouter_api_key():
            limit, source = query_openrouter_context_length(resolved_model, opener=opener)

    if limit is None or limit < 2048:
        limit = DEFAULT_CONTEXT_FALLBACK
        source = "fallback"

    if use_cache:
        _CONTEXT_CACHE[cache_key] = (limit, source, now)

    return ContextLimitInfo(active, resolved_model, limit, source, compute_reserve_tokens(limit))


def clear_context_limit_cache() -> None:
    _CONTEXT_CACHE.clear()


def default_image_sizes() -> tuple[int, int, int]:
    overview = _env_int("CIV5_OVERVIEW_MODEL_IMAGE_SIZE", "CIV5AI_OVERVIEW_MODEL_IMAGE_SIZE", default=768) or 768
    tactical = _env_int("CIV5_TACTICAL_MODEL_IMAGE_SIZE", "CIV5AI_TACTICAL_MODEL_IMAGE_SIZE", default=1024) or 1024
    overview = max(256, min(2048, overview))
    tactical = max(256, min(2048, tactical))
    return overview, tactical, 0


def initial_budget_plan() -> BudgetPlan:
    overview, tactical, focus = default_image_sizes()
    return BudgetPlan(
        overview_image_size=overview,
        tactical_image_size=tactical,
        focus_image_size=0,
        omit_focus=True,
    )


def _next_lower_image_size(size: int) -> int | None:
    for candidate in IMAGE_SIZE_LADDER:
        if candidate < size:
            return candidate
    return None


def advance_budget_plan(plan: BudgetPlan) -> bool:
    """Apply the next degradation step in David's order. Returns False if exhausted."""
    # 1. Foreign units truncated
    if plan.foreign_units != "truncated":
        plan.foreign_units = "truncated"
        plan.steps_applied.append("foreign_units=truncated")
        return True
    # 2. Story trimmed (keep >= 3)
    if plan.story != "trimmed":
        plan.story = "trimmed"
        plan.story_min_entries = STORY_MIN_ENTRIES
        plan.steps_applied.append(f"story=trimmed(min={STORY_MIN_ENTRIES})")
        return True
    # 3. Own units truncated too
    if plan.own_units != "truncated":
        plan.own_units = "truncated"
        plan.steps_applied.append("own_units=truncated")
        return True
    # 4. Chat capped to 5
    if plan.chat_max_messages != CHAT_BUDGET_MAX_MESSAGES:
        plan.chat_max_messages = CHAT_BUDGET_MAX_MESSAGES
        plan.steps_applied.append(f"chat_max={CHAT_BUDGET_MAX_MESSAGES}")
        return True
    # 5. Cities truncated
    if plan.cities != "truncated":
        plan.cities = "truncated"
        plan.steps_applied.append("cities=truncated")
        return True
    # 6. Maps LAST — omit tactical first, then step down remaining sizes
    if not plan.omit_tactical and plan.tactical_image_size > 0:
        plan.omit_tactical = True
        plan.tactical_image_size = 0
        plan.omit_focus = True
        plan.focus_image_size = 0
        plan.steps_applied.append("omit_tactical")
        return True
    next_overview = _next_lower_image_size(plan.overview_image_size)
    if next_overview is not None:
        plan.overview_image_size = next_overview
        plan.steps_applied.append(f"overview_image={next_overview}")
        return True
    # If tactical somehow still present at a high size without omit, step it
    if plan.tactical_image_size > 0:
        next_t = _next_lower_image_size(plan.tactical_image_size)
        if next_t is not None:
            plan.tactical_image_size = next_t
            plan.steps_applied.append(f"tactical_image={next_t}")
            return True
    # Final map step: drop overview entirely (text-only turn)
    if plan.overview_image_size > 0:
        plan.overview_image_size = 0
        plan.omit_tactical = True
        plan.tactical_image_size = 0
        plan.omit_focus = True
        plan.focus_image_size = 0
        plan.steps_applied.append("omit_overview")
        return True
    return False


def plan_image_sizes(plan: BudgetPlan) -> list[int]:
    sizes: list[int] = []
    if plan.overview_image_size > 0:
        sizes.append(plan.overview_image_size)
    if not plan.omit_tactical and plan.tactical_image_size > 0:
        sizes.append(plan.tactical_image_size)
    if not plan.omit_tactical and not plan.omit_focus and plan.focus_image_size > 0:
        sizes.append(plan.focus_image_size)
    return sizes


def fits_budget(estimated_prompt_tokens: int, info: ContextLimitInfo) -> bool:
    return estimated_prompt_tokens + info.reserve_tokens <= info.context_limit


def format_budget_log_line(
    info: ContextLimitInfo,
    plan: BudgetPlan,
    estimated_prompt_tokens: int,
    *,
    fits: bool | None = None,
) -> str:
    if fits is None:
        fits = fits_budget(estimated_prompt_tokens, info)
    steps = ",".join(plan.steps_applied) if plan.steps_applied else "none"
    images = plan_image_sizes(plan)
    image_txt = "x".join(str(s) for s in images) if images else "none"
    return (
        "context_budget "
        f"provider={info.provider} model={info.model or '-'} "
        f"context_limit={info.context_limit} source={info.source} "
        f"reserve={info.reserve_tokens} estimated_prompt_tokens={estimated_prompt_tokens} "
        f"prompt_budget={info.prompt_token_budget} fits={str(fits).lower()} "
        f"images={image_txt} "
        f"foreign_units={plan.foreign_units} own_units={plan.own_units} "
        f"story={plan.story} cities={plan.cities} "
        f"chat_max={plan.chat_max_messages if plan.chat_max_messages is not None else 'default'} "
        f"steps=[{steps}]"
    )


def apply_plan_to_snapshot(snapshot: dict[str, Any], plan: BudgetPlan, info: ContextLimitInfo | None = None) -> dict[str, Any]:
    """Store budget options under snapshot['advciv']['context_budget'] for wire builders."""
    advciv = snapshot.setdefault("advciv", {})
    if not isinstance(advciv, dict):
        snapshot["advciv"] = {}
        advciv = snapshot["advciv"]
    payload = plan.as_wire_options()
    if info is not None:
        payload["context_limit"] = info.context_limit
        payload["reserve_tokens"] = info.reserve_tokens
        payload["provider"] = info.provider
        payload["model"] = info.model
        payload["source"] = info.source
    advciv["context_budget"] = payload
    return payload


def read_plan_from_snapshot(snapshot: dict[str, Any] | None) -> BudgetPlan:
    plan = initial_budget_plan()
    if not isinstance(snapshot, dict):
        return plan
    advciv = snapshot.get("advciv")
    if not isinstance(advciv, dict):
        return plan
    raw = advciv.get("context_budget")
    if not isinstance(raw, dict):
        return plan
    if raw.get("foreign_units") in {"full", "truncated"}:
        plan.foreign_units = str(raw["foreign_units"])
    if raw.get("own_units") in {"full", "truncated"}:
        plan.own_units = str(raw["own_units"])
    if raw.get("story") in {"full", "trimmed"}:
        plan.story = str(raw["story"])
    if isinstance(raw.get("story_min_entries"), int) and raw["story_min_entries"] > 0:
        plan.story_min_entries = int(raw["story_min_entries"])
    if isinstance(raw.get("chat_max_messages"), int) and raw["chat_max_messages"] > 0:
        plan.chat_max_messages = int(raw["chat_max_messages"])
    if raw.get("cities") in {"full", "truncated"}:
        plan.cities = str(raw["cities"])
    if isinstance(raw.get("overview_image_size"), int):
        plan.overview_image_size = max(0, int(raw["overview_image_size"]))
    if isinstance(raw.get("tactical_image_size"), int):
        plan.tactical_image_size = max(0, int(raw["tactical_image_size"]))
    if isinstance(raw.get("focus_image_size"), int):
        plan.focus_image_size = max(0, min(512, int(raw["focus_image_size"])))
    if raw.get("omit_tactical") is True or plan.tactical_image_size == 0:
        plan.omit_tactical = True
        plan.tactical_image_size = 0
        plan.omit_focus = True
        plan.focus_image_size = 0
    if raw.get("omit_focus") is True or plan.focus_image_size == 0:
        plan.omit_focus = True
        plan.focus_image_size = 0
    steps = raw.get("steps_applied")
    if isinstance(steps, list):
        plan.steps_applied = [str(s) for s in steps]
    return plan


def choose_budget_plan(
    *,
    info: ContextLimitInfo,
    build_wire: Callable[[BudgetPlan], str],
    attach_images: bool = True,
    max_steps: int = 16,
) -> tuple[BudgetPlan, str, int]:
    """Walk the degradation ladder until estimated tokens + reserve fit (or exhausted)."""
    plan = initial_budget_plan()
    if not attach_images:
        plan.omit_tactical = True
        plan.omit_focus = True
        plan.tactical_image_size = 0
        plan.focus_image_size = 0
        plan.overview_image_size = 0
        plan.steps_applied.append("images_disabled")

    wire = build_wire(plan)
    images = plan_image_sizes(plan) if attach_images else []
    estimated = estimate_prompt_tokens(wire, image_sizes=images)
    if fits_budget(estimated, info):
        return plan, wire, estimated

    for _ in range(max_steps):
        if not advance_budget_plan(plan):
            break
        wire = build_wire(plan)
        images = plan_image_sizes(plan) if attach_images else []
        estimated = estimate_prompt_tokens(wire, image_sizes=images)
        if fits_budget(estimated, info):
            break
    return plan, wire, estimated



CONTEXT_OVERFLOW_MARKERS = (
    "context size has been exceeded",
    "context_length_exceeded",
    "context length exceeded",
    "exceeds the context",
    "maximum context length",
    "prompt is too long",
    "n_keep",
)


def is_context_overflow_error(error: BaseException | str | None) -> bool:
    """True when an LLM provider rejected the request for context overflow."""
    if error is None:
        return False
    text = str(error)
    category = str(getattr(error, "category", "") or "").lower()
    if category in {"context_overflow", "context_length", "context_size"}:
        return True
    low = text.lower()
    return any(marker in low for marker in CONTEXT_OVERFLOW_MARKERS)


def align_reserve_with_max_output(info: ContextLimitInfo, max_output_tokens: int | None) -> ContextLimitInfo:
    """Ensure reserve covers the actual max_tokens we will request from the API.

    The paragraph-based reserve (~4200) can be smaller than chat_max_output_tokens
    (often 8192 for high effort). LM Studio/llama.cpp reject when
    prompt_tokens + max_tokens > loaded_context_length — so the budgeter must
    reserve at least max_tokens.
    """
    if max_output_tokens is None:
        return info
    needed = max(0, int(max_output_tokens))
    if needed <= info.reserve_tokens:
        return info
    cap = max(0, int(info.context_limit) - 1024)
    reserve = min(cap, needed) if info.context_limit > 1024 else needed
    return ContextLimitInfo(
        info.provider, info.model, info.context_limit, info.source, reserve,
    )


def force_omit_all_images(plan: BudgetPlan) -> bool:
    """Emergency: drop every map image. Returns True if anything changed."""
    changed = False
    if plan.overview_image_size > 0 or not plan.omit_tactical or plan.tactical_image_size > 0 or plan.focus_image_size > 0:
        changed = True
    plan.overview_image_size = 0
    plan.omit_tactical = True
    plan.tactical_image_size = 0
    plan.omit_focus = True
    plan.focus_image_size = 0
    if changed and (not plan.steps_applied or plan.steps_applied[-1] != "omit_overview"):
        plan.steps_applied.append("omit_overview")
    return changed


def aggressive_shrink_for_overflow(plan: BudgetPlan, *, min_steps: int = 2) -> int:
    """Apply at least min_steps degradation steps; if exhausted, omit all images.

    Returns the number of steps applied in this call.
    """
    applied = 0
    target = max(1, int(min_steps))
    while applied < target:
        if advance_budget_plan(plan):
            applied += 1
            continue
        if force_omit_all_images(plan):
            applied += 1
        break
    return applied



__all__ = [
    "BudgetPlan",
    "ContextLimitInfo",
    "advance_budget_plan",
    "apply_plan_to_snapshot",
    "choose_budget_plan",
    "aggressive_shrink_for_overflow",
    "force_omit_all_images",
    "align_reserve_with_max_output",
    "is_context_overflow_error",
    "clear_context_limit_cache",
    "compute_reserve_tokens",
    "paragraph_output_reserve_tokens",
    "default_image_sizes",
    "estimate_prompt_tokens",
    "estimate_text_tokens",
    "estimate_vision_tokens",
    "fits_budget",
    "format_budget_log_line",
    "initial_budget_plan",
    "plan_image_sizes",
    "query_lmstudio_context_length",
    "query_openrouter_context_length",
    "read_plan_from_snapshot",
    "resolve_model_context_limit",
]
