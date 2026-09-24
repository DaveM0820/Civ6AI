"""Civ6Ai local runtime config (LM Studio defaults + env overrides).

Load order:
  1) config/civ6ai.local.json (optional, gitignored)
  2) config/civ6ai.local.example.json defaults
  3) environment variable overrides

No secrets belong in committed files — use env or a local JSON copy.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"
LOCAL_CONFIG = CONFIG_DIR / "civ6ai.local.json"
EXAMPLE_CONFIG = CONFIG_DIR / "civ6ai.local.example.json"

LMSTUDIO_BASE_DEFAULT = "http://localhost:1234/v1"
LMSTUDIO_MODEL_DEFAULT = "qwen/qwen3-vl-8b"
LMSTUDIO_API_KEY_DEFAULT = "lm-studio"
LMSTUDIO_TIMEOUT_DEFAULT = 600


@dataclass
class Civ6AiLocalConfig:
    schema_version: str = "civ6ai-local/1"
    provider: str = "lmstudio"
    endpoint: str = LMSTUDIO_BASE_DEFAULT
    model: str = LMSTUDIO_MODEL_DEFAULT
    api_key: str = LMSTUDIO_API_KEY_DEFAULT
    timeout_seconds: int = LMSTUDIO_TIMEOUT_DEFAULT
    max_retries: int = 3
    vision: bool = True
    reasoning: str = "on"  # on|off only for LM Studio Qwen stacks
    context_budget: bool = True
    queue_shared_model: bool = True
    mp_move_sync: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def chat_completions_url(self) -> str:
        return self.endpoint.rstrip("/") + "/chat/completions"

    @property
    def models_url(self) -> str:
        return self.endpoint.rstrip("/") + "/models"


_BOOL_TRUE = {"1", "true", "yes", "on"}
_BOOL_FALSE = {"0", "false", "no", "off"}


def _env_first(*names: str, default: str = "") -> str:
    for name in names:
        raw = os.environ.get(name, "").strip()
        if raw:
            return raw
    return default


def _env_bool(*names: str, default: bool) -> bool:
    for name in names:
        raw = os.environ.get(name, "").strip().lower()
        if raw in _BOOL_TRUE:
            return True
        if raw in _BOOL_FALSE:
            return False
    return default


def _env_int(*names: str, default: int) -> int:
    for name in names:
        raw = os.environ.get(name, "").strip()
        if not raw:
            continue
        try:
            return int(raw)
        except ValueError:
            continue
    return default


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    return raw if isinstance(raw, dict) else {}


def normalize_reasoning(value: Any) -> str:
    """Map config/env to LM Studio-safe on|off (never reasoning_effort=on)."""
    text = str(value or "on").strip().lower()
    if text in {"", "none", "off", "minimal", "false", "0"}:
        return "off"
    if text in {"on", "true", "1", "low", "medium", "high", "xhigh"}:
        return "on"
    return "on"


def load_local_config(
    path: Path | None = None,
    *,
    apply_env: bool = True,
) -> Civ6AiLocalConfig:
    """Load example defaults, overlay local JSON, then env overrides."""
    data: dict[str, Any] = {}
    example = _read_json(EXAMPLE_CONFIG)
    data.update({k: v for k, v in example.items() if k != "comment" and not str(k).startswith("_")})
    local_path = path or LOCAL_CONFIG
    data.update({k: v for k, v in _read_json(local_path).items() if k != "comment" and not str(k).startswith("_")})

    known = {f.name for f in fields(Civ6AiLocalConfig)}
    kwargs = {k: v for k, v in data.items() if k in known}
    cfg = Civ6AiLocalConfig(**kwargs)
    cfg.reasoning = normalize_reasoning(cfg.reasoning)
    cfg.timeout_seconds = max(30, int(cfg.timeout_seconds or LMSTUDIO_TIMEOUT_DEFAULT))
    cfg.max_retries = max(1, int(cfg.max_retries or 1))
    cfg.endpoint = str(cfg.endpoint or LMSTUDIO_BASE_DEFAULT).rstrip("/")
    cfg.model = str(cfg.model or LMSTUDIO_MODEL_DEFAULT).strip()
    cfg.provider = str(cfg.provider or "lmstudio").strip().lower()

    if not apply_env:
        return cfg

    provider = _env_first("CIV6AI_MODEL_PROVIDER", "CIV4AI_MODEL_PROVIDER", default=cfg.provider)
    cfg.provider = provider.strip().lower() or cfg.provider
    cfg.endpoint = _env_first(
        "LMSTUDIO_BASE_URL",
        "CIV6AI_LMSTUDIO_BASE_URL",
        "OPENAI_BASE_URL",
        default=cfg.endpoint,
    ).rstrip("/")
    cfg.model = _env_first("LMSTUDIO_MODEL", "CIV6AI_LMSTUDIO_MODEL", "OPENAI_MODEL", default=cfg.model)
    cfg.api_key = _env_first("LMSTUDIO_API_KEY", "CIV6AI_LMSTUDIO_API_KEY", default=cfg.api_key)
    cfg.timeout_seconds = _env_int(
        "CIV6AI_LMSTUDIO_TIMEOUT_SECONDS",
        "CIV4AI_LMSTUDIO_TIMEOUT_SECONDS",
        default=cfg.timeout_seconds,
    )
    cfg.max_retries = _env_int("CIV6AI_LMSTUDIO_MAX_RETRIES", default=cfg.max_retries)
    cfg.vision = _env_bool(
        "CIV6AI_LMSTUDIO_VISION",
        "CIV4AI_LMSTUDIO_VISION",
        default=cfg.vision,
    )
    reasoning_raw = _env_first(
        "CIV6AI_LMSTUDIO_REASONING",
        "CIV4AI_LMSTUDIO_REASONING",
        "CIV6AI_LMSTUDIO_REASONING_EFFORT",
        "CIV4AI_LMSTUDIO_REASONING_EFFORT",
        default=cfg.reasoning,
    )
    cfg.reasoning = normalize_reasoning(reasoning_raw)
    cfg.context_budget = _env_bool("CIV6AI_CONTEXT_BUDGET", default=cfg.context_budget)
    cfg.queue_shared_model = _env_bool("CIV6AI_QUEUE_SHARED_MODEL", default=cfg.queue_shared_model)
    cfg.mp_move_sync = _env_bool(
        "CIV6AI_MP_MOVE_SYNC",
        "CIV6AI_MP_MOVE_SYNC_FLAG",
        default=cfg.mp_move_sync,
    )
    cfg.timeout_seconds = max(30, int(cfg.timeout_seconds))
    cfg.max_retries = max(1, int(cfg.max_retries))
    return cfg


def apply_config_to_environ(cfg: Civ6AiLocalConfig) -> None:
    """Push config into process env so pipeline / context_budget see the same values."""
    os.environ["CIV6AI_MODEL_PROVIDER"] = cfg.provider
    os.environ["CIV4AI_MODEL_PROVIDER"] = cfg.provider
    os.environ["LMSTUDIO_BASE_URL"] = cfg.endpoint
    os.environ["LMSTUDIO_MODEL"] = cfg.model
    if cfg.api_key and "LMSTUDIO_API_KEY" not in os.environ:
        os.environ["LMSTUDIO_API_KEY"] = cfg.api_key
    os.environ["CIV6AI_LMSTUDIO_TIMEOUT_SECONDS"] = str(cfg.timeout_seconds)
    os.environ["CIV4AI_LMSTUDIO_TIMEOUT_SECONDS"] = str(cfg.timeout_seconds)
    os.environ["CIV6AI_LMSTUDIO_VISION"] = "1" if cfg.vision else "0"
    os.environ["CIV4AI_LMSTUDIO_VISION"] = "1" if cfg.vision else "0"
    os.environ["CIV6AI_LMSTUDIO_REASONING"] = cfg.reasoning
    os.environ["CIV4AI_LMSTUDIO_REASONING"] = "1" if cfg.reasoning == "on" else "0"
    # Never leave a legacy "on" effort string that LM Studio would reject.
    os.environ["CIV6AI_LMSTUDIO_REASONING_EFFORT"] = cfg.reasoning
    os.environ["CIV4AI_LMSTUDIO_REASONING_EFFORT"] = cfg.reasoning
    os.environ["CIV6AI_CONTEXT_BUDGET"] = "1" if cfg.context_budget else "0"
    os.environ["CIV6AI_QUEUE_SHARED_MODEL"] = "1" if cfg.queue_shared_model else "0"
    if cfg.mp_move_sync:
        os.environ["CIV6AI_MP_MOVE_SYNC"] = "1"
    elif "CIV6AI_MP_MOVE_SYNC" not in os.environ:
        os.environ["CIV6AI_MP_MOVE_SYNC"] = "0"
