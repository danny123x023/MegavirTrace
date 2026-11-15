"""Admin panel: sign-in sessions and the AI service settings (keys, active service, fallback)."""

from __future__ import annotations

import json
import os
import stat

import pytest

from megavir import ai
from megavir.ai import config
from megavir.config import settings
from megavir.imports.admin import browser_label
from tests.conftest import ORIGIN

ANTHROPIC_KEY = "sk-ant-api03-" + "x" * 40 + "WXYZ"
ZAI_KEY = "zai-" + "y" * 30 + "abcd"
# a request through the web app's proxy: never "this computer", so only a session or token counts
VIA_PROXY = {**ORIGIN, "X-Forwarded-Host": "localhost:3000"}


@pytest.fixture
def ai_file(tmp_path, monkeypatch):
    path = tmp_path / "ai_settings.json"
    monkeypatch.setattr(settings(), "ai_settings_file", str(path))
    monkeypatch.setattr(settings(), "ai_provider", "none")
    monkeypatch.setattr(settings(), "ai_api_key", "")
    monkeypatch.setattr(settings(), "ai_model", "")
    monkeypatch.setattr(config, "_cache", None)
    return path


def test_keys_are_kept_server_side_and_shown_only_as_a_hint(ai_file):
    config.set_key("anthropic", ANTHROPIC_KEY)
    assert stat.S_IMODE(os.stat(ai_file).st_mode) == 0o600
    pub = config.public()
    assert ANTHROPIC_KEY not in json.dumps(pub)
    a = pub["providers"]["anthropic"]
    assert a["key_hint"] == "…WXYZ" and a["key_source"] == "panel"
    assert a["model"] == "claude-opus-5-5" and a["ready"]  # Claude has a default model
    assert pub["active"] == "none"  # a key alone does not switch the AI on


@pytest.mark.parametrize(
    ("p", "key", "message"),
    [
        ("anthropic", "sk-ant-admin01-" + "a" * 30, "Admin API key"),
        ("anthropic", "abc-" + "a" * 30, "start with sk-ant-"),
        ("zai", "short", "does not look like"),
        ("zai", "has space " + "a" * 20, "does not look like"),
        ("openai", "a" * 30, "unknown AI service"),
    ],
)
def test_key_format_is_checked(ai_file, p, key, message):
    with pytest.raises(config.SettingsError, match=message):
        config.set_key(p, key)


def test_choosing_the_service_model_and_fallback(ai_file):
    with pytest.raises(config.SettingsError, match="needs a key and a model"):
        config.set_choice("zai")
    config.set_key("zai", ZAI_KEY)
    with pytest.raises(config.SettingsError, match="needs a key and a model"):
        config.set_choice("zai")  # Z.ai has no default model
    config.set_choice("zai", models={"zai": "glm-5.3"})  # model and service in one step
    assert config.active() == "zai" and config.provider("zai")["model"] == "glm-5.3"
    config.set_key("anthropic", ANTHROPIC_KEY)
    assert config.fallback() is None  # off until chosen
    config.set_choice(fallback_on=True)
    assert config.fallback() == "anthropic"
    config.remove_key("zai")
    assert config.active() == "none"  # the chosen service lost its key
    with pytest.raises(config.SettingsError, match="1 to 80"):
        config.set_choice(models={"anthropic": "bad model name!"})


def test_env_settings_still_apply_without_the_panel(ai_file, monkeypatch):
    monkeypatch.setattr(settings(), "ai_provider", "zai")
    monkeypatch.setattr(settings(), "ai_api_key", ZAI_KEY)
    monkeypatch.setattr(settings(), "ai_model", "glm-5.3")
    assert config.active() == "zai"
    z = config.public()["providers"]["zai"]
    assert z["key_source"] == "env" and z["key_hint"] == "…abcd"
    config.set_choice("none")  # the panel overrides .env
    assert config.active() == "none"


def test_the_other_service_takes_over_when_allowed(ai_file, monkeypatch):
    config.set_key("zai", ZAI_KEY)
    config.set_key("anthropic", ANTHROPIC_KEY)
    config.set_choice("zai", models={"zai": "glm-5.3"})
    calls = []

    def fake(p, messages, system, ctx):
        calls.append((p, len(messages)))
        messages.append({"role": "assistant", "content": "partial"})  # the loops append
        if p == "zai":
            raise ai.ProviderError("AI service error 500")
        return {"headline": "h", "explanation": "e"}, 1, 2

    monkeypatch.setattr(ai, "_call_one", fake)
    ctx: dict = {}
    with pytest.raises(ai.ProviderError):
        ai._call([{"role": "user", "content": "q"}], "s", ctx)  # fallback is off
    config.set_choice(fallback_on=True)
    calls.clear()
    out = ai._call([{"role": "user", "content": "q"}], "s", ctx)
    assert out[0]["headline"] == "h"
    assert calls == [("zai", 1), ("anthropic", 1)]  # the second service starts from the question
    assert ctx["served_by"]["provider"] == "anthropic" and "zai" in ctx["served_by"]["after"]


def test_browser_label():
    chrome = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141 Safari/537.36"
    assert browser_label(chrome) == "Chrome on Windows"
    assert browser_label("curl/8.5.0") == "curl"


# ---- through the API (sessions are stored in the database) ---------------------------------------


@pytest.fixture
def token(monkeypatch):
    monkeypatch.setattr(settings(), "admin_token", "test-admin-token")
    return "test-admin-token"


@pytest.mark.db
def test_sign_in_sessions(client, token):
    assert client.post("/admin/sessions", json={"token": "wrong"}, headers=VIA_PROXY).status_code == 403
    r = client.post("/admin/sessions", json={"token": token, "remember": True}, headers=VIA_PROXY).json()
    secret = r["session"]
    assert r["info"]["remember"] and r["info"]["current"]
    me = {**VIA_PROXY, "X-Admin-Session": secret}
    assert client.get("/admin/overview", headers=me).json()["role"] == "admin"
    assert client.get("/admin/overview", headers=VIA_PROXY).json()["role"] is None
    other = client.post("/admin/sessions", json={"token": token}, headers=VIA_PROXY).json()["session"]
    listed = client.get("/admin/sessions", headers=me).json()["sessions"]
    assert sum(s["current"] for s in listed) == 1 and len(listed) >= 2
    assert all(secret not in json.dumps(s) for s in listed)  # never the secret, only an id
    # sign out everywhere else: the other session ends, this one stays
    assert client.delete("/admin/sessions", headers=me).json()["ended"] >= 1
    assert (
        client.get("/admin/overview", headers={**VIA_PROXY, "X-Admin-Session": other}).json()["role"] is None
    )
    assert client.delete("/admin/sessions/current", headers=me).json()["ended"]
    assert client.get("/admin/sessions", headers=me).status_code == 403


@pytest.mark.db
def test_ai_settings_through_the_api(client, token, ai_file, monkeypatch):
    me = {**VIA_PROXY, "X-Admin-Token": token}
    assert client.get("/admin/ai", headers=VIA_PROXY).status_code == 403
    monkeypatch.setattr(
        ai,
        "test_key",
        lambda p, key=None, model=None: {"ok": key != "sk-ant-api03-" + "z" * 40, "detail": "checked"},
    )
    bad = client.put("/admin/ai/keys/anthropic", json={"api_key": "sk-ant-api03-" + "z" * 40}, headers=me)
    assert bad.status_code == 422 and not config.load()["keys"]  # refused keys are not saved
    r = client.put("/admin/ai/keys/anthropic", json={"api_key": ANTHROPIC_KEY}, headers=me)
    assert r.status_code == 200 and ANTHROPIC_KEY not in r.text
    assert r.json()["providers"]["anthropic"]["key_hint"] == "…WXYZ"
    v = client.put(
        "/admin/ai", json={"active": "anthropic", "models": {"anthropic": "claude-sonnet-5-5"}}, headers=me
    ).json()
    assert v["active"] == "anthropic" and v["providers"]["anthropic"]["model"] == "claude-sonnet-5-5"
    assert client.get("/ai/status").json()["provider"] == "anthropic"
    assert client.put("/admin/ai", json={"active": "zai"}, headers=me).status_code == 422  # no key
    assert client.delete("/admin/ai/keys/anthropic", headers=me).json()["active"] == "none"
