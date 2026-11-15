"""Which AI service answers, with which key and model: chosen in the Admin panel.

Two services can be set up side by side: Claude (Anthropic) and Z.ai (GLM).  Their keys, the
model of each, which one is active and whether the other one takes over when the active one
fails are kept in one owner-only file on the server (MEGAVIR_AI_SETTINGS_FILE, default
data/ai_settings.json), written atomically.  Keys never leave the server: the panel sees only a
hint ("…abcd").  The file is read on every use, so every API process sees a change at once.

Without the file (or for anything it leaves out) the .env settings apply as before:
MEGAVIR_AI_PROVIDER, MEGAVIR_AI_MODEL and MEGAVIR_AI_API_KEY (the key of that provider).
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import threading
from pathlib import Path

from megavir.config import settings

PROVIDERS = ("anthropic", "zai")  # managed in the panel
ENV_ONLY = ("openai", "openai_compatible")  # still possible from .env
LABELS = {"anthropic": "Claude (Anthropic)", "zai": "Z.ai (GLM)"}
DEFAULT_MODELS = {"anthropic": "claude-opus-5-5"}
SUGGESTED_MODELS = {
    "anthropic": ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-2"],
    "zai": ["glm-5.3"],
}
MODEL_RE = re.compile(r"[A-Za-z0-9._:/-]{1,80}")

_lock = threading.Lock()
_cache: tuple[float, dict] | None = None


class SettingsError(ValueError):
    pass


def settings_file() -> Path:
    return (
        Path(settings().ai_settings_file)
        if settings().ai_settings_file
        else settings().data_dir / "ai_settings.json"
    )


def _empty() -> dict:
    return {"active": None, "fallback": False, "keys": {}, "models": {}, "updated_at": None}


def load() -> dict:
    """The panel's settings (empty when nothing was chosen there)."""
    global _cache
    path = settings_file()
    try:
        mtime = path.stat().st_mtime
    except FileNotFoundError:
        return _empty()
    if _cache and _cache[0] == mtime:
        return json.loads(json.dumps(_cache[1]))
    try:
        data = {**_empty(), **json.loads(path.read_text())}
    except (OSError, json.JSONDecodeError):
        return _empty()
    _cache = (mtime, data)
    return json.loads(json.dumps(data))


def _save(data: dict) -> None:
    path = settings_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {**data, "updated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds")}
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(data, fh, indent=1)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def _update(fn) -> dict:
    with _lock:
        data = load()
        fn(data)
        _save(data)
        return data


# --------------------------------------------------------------------------------------
# What applies now
# --------------------------------------------------------------------------------------


def _env_provider() -> str:
    return (settings().ai_provider or "none").lower()


def provider(p: str, data: dict | None = None) -> dict:
    """Key, model and where they come from, for one service."""
    data = data if data is not None else load()
    s = settings()
    env = _env_provider() == p
    key = data["keys"].get(p) or (s.ai_api_key if env else "")
    source = "panel" if data["keys"].get(p) else ("env" if env and s.ai_api_key else None)
    model = data["models"].get(p) or (s.ai_model if env and s.ai_model else DEFAULT_MODELS.get(p, ""))
    return {
        "key": key,
        "key_source": source,
        "model": model,
        "base_url": s.ai_base_url if (env and p in ENV_ONLY) else "",
    }


def ready(p: str, data: dict | None = None) -> bool:
    cfg = provider(p, data)
    return bool(cfg["key"] and cfg["model"])


def active() -> str:
    """The service that answers now ("none" when off or not set up)."""
    chosen = load().get("active")
    p = chosen if chosen else _env_provider()
    if p not in PROVIDERS + ENV_ONLY:
        return "none"
    return p if ready(p) else "none"


def fallback() -> str | None:
    """The service that takes over when the active one fails, if switched on and set up."""
    a = active()
    if a not in PROVIDERS or not load().get("fallback"):
        return None
    other = next(p for p in PROVIDERS if p != a)
    return other if ready(other) else None


def hint(key: str) -> str:
    return f"…{key[-4:]}" if len(key) >= 12 else "…"


def public() -> dict:
    """Everything the Admin panel shows (no key, only its last four characters)."""
    data = load()
    out = {}
    for p in PROVIDERS:
        cfg = provider(p)
        out[p] = {
            "label": LABELS[p],
            "key_set": bool(cfg["key"]),
            "key_hint": hint(cfg["key"]) if cfg["key"] else None,
            "key_source": cfg["key_source"],
            "model": cfg["model"],
            "suggested_models": SUGGESTED_MODELS[p],
            "ready": ready(p),
        }
    chosen = data.get("active")
    return {
        "active": active(),
        "chosen": chosen or _env_provider(),
        "chosen_in": "panel" if chosen else "env",
        "fallback": bool(data.get("fallback")),
        "fallback_to": fallback(),
        "providers": out,
        "updated_at": data.get("updated_at"),
        "file": str(settings_file()),
    }


# --------------------------------------------------------------------------------------
# Changes from the panel
# --------------------------------------------------------------------------------------


def check_key_format(p: str, key: str) -> str:
    key = (key or "").strip()
    if p not in PROVIDERS:
        raise SettingsError("unknown AI service")
    if not 10 <= len(key) <= 300 or re.search(r"\s", key):
        raise SettingsError("that does not look like an API key")
    if p == "anthropic":
        if key.startswith("sk-ant-admin"):
            raise SettingsError("that is an Anthropic Admin API key; use a regular API key (sk-ant-api…)")
        if not key.startswith("sk-ant-"):
            raise SettingsError("Anthropic API keys start with sk-ant-")
    return key


def check_model(model: str) -> str:
    model = (model or "").strip()
    if not MODEL_RE.fullmatch(model):
        raise SettingsError("a model name has 1 to 80 letters, digits and . _ : / -")
    return model


def set_key(p: str, key: str) -> dict:
    key = check_key_format(p, key)
    return _update(lambda d: d["keys"].__setitem__(p, key))


def remove_key(p: str) -> dict:
    if p not in PROVIDERS:
        raise SettingsError("unknown AI service")
    return _update(lambda d: d["keys"].pop(p, None))


def set_choice(
    active_p: str | None = None, fallback_on: bool | None = None, models: dict | None = None
) -> dict:
    if active_p is not None and active_p not in PROVIDERS + ("none",):
        raise SettingsError("choose anthropic, zai or none")
    clean = {p: check_model(m) for p, m in (models or {}).items() if p in PROVIDERS}

    def change(d: dict) -> None:
        d["models"].update(clean)  # a model chosen together with the service counts
        if active_p in PROVIDERS and not ready(active_p, d):
            raise SettingsError(f"{LABELS[active_p]} needs a key and a model first")
        if active_p is not None:
            d["active"] = active_p
        if fallback_on is not None:
            d["fallback"] = bool(fallback_on)

    return _update(change)


__all__ = [
    "LABELS",
    "PROVIDERS",
    "SettingsError",
    "active",
    "fallback",
    "provider",
    "public",
    "ready",
    "remove_key",
    "set_choice",
    "set_key",
]
