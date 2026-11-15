"""AI Earth Scientist (FR13, optional) and its cost controls (FR20).

The AI never computes.  It turns a question into calls to the engine (tools), then explains
the stored results.  Every number and every direction word it writes is checked against the
analyses it cites; if the check fails, or the service fails, or a limit is reached, the
visitor gets the template verdict instead.  The statistics cards are always drawn from the
stored analysis JSON, never from the AI's text.

Services (set in the server's configuration only, never sent to the browser):
* OpenAI-style chat completions: Z.ai GLM (default), OpenAI, or any compatible service;
* Anthropic Messages API (official SDK), with structured output.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import time

import httpx

from megavir.api import service
from megavir.api.security import SlidingWindow
from megavir.catalog import VARIABLES
from megavir.config import settings
from megavir.store import connect

from . import config
from .numbers import allowed_numbers, check_text

log = logging.getLogger("megavir.ai")

BASE_URLS = {
    "zai": "https://api.z.ai/api/paas/v4",
    "openai": "https://api.openai.com/v1",
}
MAX_TOOL_ROUNDS = 6

_hourly: SlidingWindow | None = None


def _limiter() -> SlidingWindow:
    global _hourly
    if _hourly is None:
        _hourly = SlidingWindow(settings().ai_hourly_limit_per_ip, 3600.0)
    return _hourly


# --------------------------------------------------------------------------------------
# Status, usage records and limits
# --------------------------------------------------------------------------------------


def _provider() -> str:
    """The active service (Admin panel, else .env), or "none"."""
    return config.active()


def _model() -> str:
    p = _provider()
    return config.provider(p)["model"] if p != "none" else ""


def status() -> dict:
    p = _provider()
    return {
        "enabled": p != "none" and bool(_model()),
        "provider": p,
        "model": _model() if p != "none" else None,
        "hourly_limit_per_visitor": settings().ai_hourly_limit_per_ip,
        "daily_cap": settings().ai_daily_cap,
        "used_today": _used_today(),
    }


def _used_today() -> int:
    try:
        with connect() as conn:
            r = conn.execute(
                "SELECT coalesce(sum(n), 0) AS n FROM ai_usage WHERE day = %s AND outcome IN ('answered','fallback','failed')",
                (dt.date.today(),),
            ).fetchone()
            return int(r["n"])
    except Exception:  # noqa: BLE001
        return 0


def _record(outcome: str, tokens_in: int = 0, tokens_out: int = 0) -> None:
    try:
        with connect() as conn:
            conn.execute(
                """INSERT INTO ai_usage (day, outcome, n, tokens_in, tokens_out) VALUES (%s, %s, 1, %s, %s)
                   ON CONFLICT (day, outcome) DO UPDATE SET n = ai_usage.n + 1,
                   tokens_in = ai_usage.tokens_in + EXCLUDED.tokens_in, tokens_out = ai_usage.tokens_out + EXCLUDED.tokens_out""",
                (dt.date.today(), outcome, tokens_in, tokens_out),
            )
            conn.commit()
        log.info("ai outcome=%s tokens_in=%d tokens_out=%d", outcome, tokens_in, tokens_out)
    except Exception:  # noqa: BLE001
        log.exception("could not record AI usage")


def _gate(ip: str) -> str | None:
    """None if the AI may answer; otherwise the reason it may not."""
    if _provider() == "none" or not _model():
        return "The AI scientist is switched off on this server."
    ok, retry = _limiter().allow(ip)
    if not ok:
        _record("limited")
        return f"You have asked a lot of questions this hour. Please try again in about {max(1, retry // 60)} minutes."
    if _used_today() >= settings().ai_daily_cap:
        _record("limited")
        return "The AI scientist has reached today's limit. The computed results below are always available."
    return None


# --------------------------------------------------------------------------------------
# Tools: the only way the AI reaches data
# --------------------------------------------------------------------------------------

REGION_SCHEMA = {
    "type": "object",
    "description": "The place: simplest is place_name (looked up for you). Or a place id from find_places "
    "(e.g. 'country:BRA', 'admin1:US-TX', 'preset:sahel'), or a box.",
    "properties": {
        "place_name": {
            "type": "string",
            "description": "A place name as the visitor wrote it, e.g. 'Sahel', 'Texas', 'Brazil', 'Tokyo'.",
        },
        "place": {"type": "string"},
        "bbox": {
            "type": "array",
            "items": {"type": "number"},
            "description": "[west, south, east, north] degrees",
        },
    },
    "additionalProperties": False,
}

# the variable ids are in the tools themselves, so the AI does not need a round trip to look them up
VARIABLE_SCHEMA = {
    "type": "string",
    "enum": list(VARIABLES),
    "description": "; ".join(f"{v.id}: {v.name}" for v in VARIABLES.values()),
}

TOOLS = [
    {
        "name": "list_variables",
        "description": "Units, sources and record spans of every variable (only if you need those; the ids are "
        "listed in the analysis tools).",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "find_places",
        "description": "Search places by name (countries, states, cities, preset regions). Only needed when a "
        "place_name was not found or is ambiguous: the analysis tools look names up themselves.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "run_trend_analysis",
        "description": "Run the deterministic trend engine for one variable in one region. Returns an analysis id and the stored statistics. "
        "mode: annual (default), season (with season DJF/MAM/JJA/SON) or monthly.",
        "input_schema": {
            "type": "object",
            "properties": {
                "variable": VARIABLE_SCHEMA,
                "region": REGION_SCHEMA,
                "mode": {"type": "string", "enum": ["annual", "season", "monthly"]},
                "season": {"type": "string", "enum": ["DJF", "MAM", "JJA", "SON"]},
                "start_year": {"type": "integer"},
                "end_year": {"type": "integer"},
            },
            "required": ["variable", "region"],
            "additionalProperties": False,
        },
    },
    {
        "name": "compare_regions",
        "description": "Test whether one variable's trend really differs between two regions (test on the difference series).",
        "input_schema": {
            "type": "object",
            "properties": {
                "variable": VARIABLE_SCHEMA,
                "region_a": REGION_SCHEMA,
                "region_b": REGION_SCHEMA,
                "mode": {"type": "string", "enum": ["annual", "season", "monthly"]},
                "season": {"type": "string", "enum": ["DJF", "MAM", "JJA", "SON"]},
            },
            "required": ["variable", "region_a", "region_b"],
            "additionalProperties": False,
        },
    },
    {
        "name": "scan_region",
        "description": "Test every loaded variable for one region, with false-discovery control across variables.",
        "input_schema": {
            "type": "object",
            "properties": {"region": REGION_SCHEMA},
            "required": ["region"],
            "additionalProperties": False,
        },
    },
]

FINAL_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "explanation": {"type": "string"},
        "analysis_ids": {"type": "array", "items": {"type": "string"}},
        "follow_up_questions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["headline", "explanation", "analysis_ids", "follow_up_questions"],
    "additionalProperties": False,
}


def _card(r: dict) -> dict:
    """What the AI sees of a stored analysis: the engine's numbers, nothing computed by the AI."""
    if r["kind"] == "trend":
        st = r["stats"]
        return {
            "analysis_id": r["id"],
            "variable": r["variable"]["name"],
            "region": r["region"]["name"],
            "units": r["units"],
            "period": f"{r['series']['labels'][0]} to {r['series']['labels'][-1]}",
            "per_decade": {k: _r(v) for k, v in st["per_decade"].items()},
            "p_mann_kendall": _r(st["mk"]["p"]),
            "p_least_squares": _r(st["ols"]["p"]),
            "significant": st["significant"],
            "direction": st["direction"],
            "years_needed_to_detect": _r(st["years_needed"]),
            "more_years_needed": _r(st["years_more"]),
            "size_against_noise": st["effect_label"],
            "fragile": st["robustness"]["fragile"],
            "verdict": r["verdict"]["headline"],
            "verdict_sentences": r["verdict"]["sentences"],
            "caveats": r["verdict"]["caveats"],
            "data_kind": r["data"]["kind"],
        }
    d = r["comparison"]["difference"]
    return {
        "analysis_id": r["id"],
        "variable": r["variable"]["name"],
        "region_a": r["region_a"]["name"],
        "region_b": r["region_b"]["name"],
        "units": r["units"],
        "difference_per_decade": _r(d["slope_per_decade"]),
        "ci_per_decade": [_r(d["ci_low_per_decade"]), _r(d["ci_high_per_decade"])],
        "p": _r(d["p"]),
        "significant": d["significant"],
        "smallest_detectable_per_decade": _r(d["min_detectable_per_decade"]),
        "verdict": r["verdict"]["headline"],
        "verdict_sentences": r["verdict"]["sentences"],
        "data_kind": r["data"]["kind"],
    }


def _r(v, sig: int = 4):
    if isinstance(v, int | float) and v == v and abs(v) != float("inf"):
        return float(f"{v:.{sig}g}")
    return v


def _region(conn, spec, used: list[str]) -> dict:
    """A region from the AI for the engine: a place name is looked up here (no extra AI round trip).

    The place each name resolved to is noted in ``used`` so the AI can check it was the one meant."""
    spec = dict(spec) if isinstance(spec, dict) else {}
    name = str(spec.pop("place_name", "") or "").strip()
    if spec.get("place") or spec.get("bbox"):
        return spec
    if not name:
        raise service.AnalysisError("give the place: region.place_name, a place id or a box")
    from megavir.api.main import places_search

    hits = places_search(q=name[:80], limit=1)["results"]
    if not hits:
        raise service.AnalysisError(
            f"no place called {name!r} was found; try find_places with another spelling"
        )
    hit = hits[0]
    used.append(
        f"{name} -> {hit['name']}"
        + (f" ({hit['context']})" if hit.get("context") else "")
        + f" [{hit['id']}]"
    )
    return {"place": hit["id"]}


def _place_label(conn, spec: dict) -> str:
    if spec.get("place"):
        r = conn.execute("SELECT name FROM place WHERE id = %s", (spec["place"],)).fetchone()
        return r["name"] if r else spec["place"]
    return "the box you drew" if spec.get("bbox") else ""


def run_tool(name: str, args: dict, ctx: dict) -> dict:
    lang = ctx["lang"]
    with connect() as conn:
        used: list[str] = []
        try:
            for key in ("region", "region_a", "region_b"):
                if key in args:
                    args = {**args, key: _region(conn, args[key], used)}
            var = VARIABLES.get(str(args.get("variable", "")))
            _emit(
                ctx,
                {
                    "step": "tool",
                    "tool": name,
                    "variable": var.local(lang)["name"] if var else None,
                    "places": [
                        _place_label(conn, args[k]) for k in ("region", "region_a", "region_b") if k in args
                    ],
                    "query": str(args.get("query", ""))[:80] or None,
                },
            )
            out = _run_tool(conn, name, args, ctx, lang)
            if used and isinstance(out, dict):
                out = {"places_used": used, **out}
            return out
        except service.AnalysisError as e:
            return {"error": str(e), **({"places_used": used} if used else {})}


def _run_tool(conn, name: str, args: dict, ctx: dict, lang: str) -> dict:
    """The tools themselves (regions already resolved)."""
    if name == "list_variables":
        cat = service.catalog_with_status(conn)
        return {
            "variables": [
                {
                    "id": v["id"],
                    "name": v["name"],
                    "theme": v["theme"],
                    "units": v["units"],
                    "source": v["source_badge"],
                    "loaded": bool(v["data"]),
                    "data_kind": (v["data"] or {}).get("kind"),
                    "record": [
                        (v["data"] or {}).get("first_month"),
                        (v["data"] or {}).get("last_month"),
                    ],
                }
                for v in cat["variables"]
            ]
        }
    if name == "find_places":
        from megavir.api.main import places_search

        return places_search(q=str(args.get("query", ""))[:80], limit=8)
    if name == "run_trend_analysis":
        r = service.run_trend(conn, {**args, "cell_map": False, "lang": lang})
        ctx["analyses"][r["id"]] = r
        return _card(r)
    if name == "compare_regions":
        r = service.run_compare(conn, {**args, "lang": lang})
        ctx["analyses"][r["id"]] = r
        return _card(r)
    if name == "scan_region":
        s = service.run_scan(conn, {"region": args.get("region") or {}, "lang": lang})
        for row in s["results"]:
            if row.get("analysis_id"):
                rep = service.get_report(conn, row["analysis_id"])
                if rep:
                    ctx["analyses"][row["analysis_id"]] = rep["result"]
        return {
            "region": s["region"]["name"],
            "results": [
                {
                    k: _r(v)
                    for k, v in row.items()
                    if k
                    in (
                        "variable",
                        "name",
                        "per_decade",
                        "units",
                        "direction",
                        "significant",
                        "q",
                        "passes_fdr",
                        "headline",
                        "analysis_id",
                        "error",
                    )
                }
                for row in s["results"]
            ],
            "note": s["note"],
        }
    return {"error": f"unknown tool {name}"}


SYSTEM = """You are the AI Earth scientist inside MegavirTrace, a tool that tells the public, honestly, whether a place is really changing, using NASA data.

Rules you must follow:
- You never compute anything. All numbers come from the tools, which run MegavirTrace's deterministic trend engine. Copy numbers exactly as the tools give them (you may round to fewer digits). Never convert units, never calculate differences, totals, percentages or per-century values yourself.
- Call run_trend_analysis, compare_regions or scan_region before saying anything about a trend. Name the place directly (region.place_name, as the visitor wrote it); the tool looks it up and tells you which place it used. Use find_places only if a name was not found or the place used is not the one meant. If the question needs several analyses, ask for all of them at once, in the same turn. If a tool returns an error, say what is missing instead of guessing.
- "Significant" means both corrected tests agree. Do not call a trend significant unless the tool says significant: true. A non-significant result is still interesting: say how many more years would be needed when the tool gives it.
- A trend is not a cause. Never claim a cause; you may say what scientists commonly consider, marked clearly as context, not as a finding.
- If the data are test or synthetic data, say so plainly.
- Write in plain, everyday words for someone with no science background. Short sentences. Answer in the visitor's language: {lang}.
- Keep it short: the page also shows each result card with its numbers. Final answer: JSON with headline (one sentence), explanation (one or two short paragraphs, at most 120 words in total), analysis_ids (the ids you used), follow_up_questions (up to 3 short questions)."""

TUTOR = """
Tutor mode: you are a Socratic tutor. Instead of explaining the answer outright, guide the learner with questions that help them read the chart and the statistics themselves (for example: "What does the 95% range tell you if it crosses zero?"). Still run the analyses so your hints rest on real results, and still follow every rule above. Put your guiding questions in follow_up_questions."""


# --------------------------------------------------------------------------------------
# Providers
# --------------------------------------------------------------------------------------


class ProviderError(RuntimeError):
    pass


def _emit(ctx: dict, event: dict) -> None:
    """Tell the page what is happening (Ask page progress); never fails the answer."""
    cb = ctx.get("progress")
    if cb:
        try:
            cb(event)
        except Exception:  # noqa: BLE001
            log.debug("progress callback failed", exc_info=True)


def _model_round(ctx: dict, started: float) -> None:
    ctx.setdefault("timing", {"model_s": [], "tools": []})["model_s"].append(round(time.time() - started, 2))


def _tool_timed(name: str, args: dict, ctx: dict) -> dict:
    t0 = time.time()
    out = run_tool(name, args, ctx)
    ctx.setdefault("timing", {"model_s": [], "tools": []})["tools"].append([name, round(time.time() - t0, 2)])
    return out


def _anthropic_loop(messages: list[dict], system: str, ctx: dict, cfg: dict) -> tuple[dict, int, int]:
    """Anthropic Messages API (official SDK): manual tool loop, structured final answer."""
    import anthropic

    client = anthropic.Anthropic(api_key=cfg["key"], timeout=settings().ai_timeout_s, max_retries=1)
    model = cfg["model"]
    tin = tout = 0
    tools = [{**t, "strict": True} for t in TOOLS]
    kwargs = {}
    if model in (
        "claude-opus-5-5",
        "claude-fable-5-2",
        "claude-fable-5-1",
        "claude-opus-5",
        "claude-sonnet-5-5",
    ):
        # server-side fallback on a policy decline (re-runs the same request on a fallback model)
        kwargs = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
    for rnd in range(MAX_TOOL_ROUNDS + 1):
        _emit(ctx, {"step": "thinking", "round": rnd + 1})
        started = time.time()
        try:
            resp = client.beta.messages.create(
                model=model,
                max_tokens=settings().ai_max_tokens,
                system=system,
                tools=tools,
                messages=messages,
                output_config={"effort": "medium", "format": {"type": "json_schema", "schema": FINAL_SCHEMA}},
                **kwargs,
            )
        except anthropic.APIStatusError as e:
            raise ProviderError(f"Anthropic API error {e.status_code}") from e
        except anthropic.APIConnectionError as e:
            raise ProviderError("Anthropic API not reachable") from e
        _model_round(ctx, started)
        tin += getattr(resp.usage, "input_tokens", 0) or 0
        tout += getattr(resp.usage, "output_tokens", 0) or 0
        if resp.stop_reason == "refusal":
            raise ProviderError("the model declined to answer")
        if resp.stop_reason == "max_tokens":
            raise ProviderError("the answer was cut off")
        tool_uses = [b for b in resp.content if b.type == "tool_use"]
        if resp.stop_reason == "tool_use" and tool_uses:
            messages.append({"role": "assistant", "content": resp.content})
            results = []
            for tu in tool_uses:
                out = _tool_timed(tu.name, tu.input if isinstance(tu.input, dict) else {}, ctx)
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tu.id,
                        "content": json.dumps(out, default=str)[:20000],
                        "is_error": "error" in out,
                    }
                )
            messages.append({"role": "user", "content": results})
            continue
        text = next((b.text for b in resp.content if b.type == "text"), "")
        try:
            return json.loads(text), tin, tout
        except json.JSONDecodeError as e:
            raise ProviderError("the answer was not valid JSON") from e
    raise ProviderError("too many tool rounds")


def _openai_loop(messages: list[dict], system: str, ctx: dict, p: str, cfg: dict) -> tuple[dict, int, int]:
    """OpenAI-style chat completions (Z.ai GLM, OpenAI or a compatible service)."""
    base = (cfg["base_url"] or BASE_URLS.get(p, "")).rstrip("/")
    if not base.startswith("https://"):
        raise ProviderError("the AI service address must be https")
    url = base + "/chat/completions"
    headers = {"Authorization": f"Bearer {cfg['key']}", "Content-Type": "application/json"}
    tools = [
        {
            "type": "function",
            "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]},
        }
        for t in TOOLS
    ]
    msgs = [{"role": "system", "content": system}, *messages]
    tin = tout = 0
    with httpx.Client(timeout=settings().ai_timeout_s) as client:
        for rnd in range(MAX_TOOL_ROUNDS + 1):
            _emit(ctx, {"step": "thinking", "round": rnd + 1})
            started = time.time()
            body = {
                "model": cfg["model"],
                "messages": msgs,
                "tools": tools,
                "tool_choice": "auto",
                "max_tokens": settings().ai_max_tokens,
            }
            if p == "zai":  # GLM's step-by-step "thinking" is slow and eats the token budget
                body["thinking"] = {"type": "enabled" if settings().ai_thinking else "disabled"}
            try:
                r = client.post(url, headers=headers, json=body)
            except httpx.HTTPError as e:
                raise ProviderError("AI service not reachable") from e
            if r.status_code >= 400:
                raise ProviderError(f"AI service error {r.status_code}")
            _model_round(ctx, started)
            data = r.json()
            usage = data.get("usage") or {}
            tin += int(usage.get("prompt_tokens") or 0)
            tout += int(usage.get("completion_tokens") or 0)
            choice = (data.get("choices") or [{}])[0]
            msg = choice.get("message") or {}
            calls = msg.get("tool_calls") or []
            if calls:
                msgs.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls})
                for c in calls:
                    fn = c.get("function") or {}
                    try:
                        args = json.loads(fn.get("arguments") or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    out = _tool_timed(fn.get("name", ""), args if isinstance(args, dict) else {}, ctx)
                    msgs.append(
                        {
                            "role": "tool",
                            "tool_call_id": c.get("id"),
                            "content": json.dumps(out, default=str)[:20000],
                        }
                    )
                continue
            text = (msg.get("content") or "").strip()
            if text.startswith("```"):
                text = text.strip("`").split("\n", 1)[-1].rsplit("```", 1)[0]
            try:
                parsed = json.loads(text[text.find("{") : text.rfind("}") + 1])
            except (json.JSONDecodeError, ValueError) as e:
                raise ProviderError("the answer was not valid JSON") from e
            # some models (GLM) give the explanation as a list of paragraphs
            if isinstance(parsed.get("explanation"), list) and all(
                isinstance(x, str) for x in parsed["explanation"]
            ):
                parsed["explanation"] = "\n\n".join(parsed["explanation"])
            for k in ("headline", "explanation"):
                if not isinstance(parsed.get(k), str):
                    raise ProviderError("the answer is missing fields")
            parsed.setdefault("analysis_ids", [])
            parsed.setdefault("follow_up_questions", [])
            return parsed, tin, tout
    raise ProviderError("too many tool rounds")


def _call_one(p: str, messages: list[dict], system: str, ctx: dict) -> tuple[dict, int, int]:
    cfg = config.provider(p)
    if p == "anthropic":
        return _anthropic_loop(messages, system, ctx, cfg)
    return _openai_loop(messages, system, ctx, p, cfg)


def _call(messages: list[dict], system: str, ctx: dict) -> tuple[dict, int, int]:
    """Ask the active service; if it fails and the panel allows it, the other one takes over.

    Records which service and model answered in ctx["served_by"]."""
    p = _provider()
    first = list(messages)  # the loops append to the list they get
    try:
        out = _call_one(p, messages, system, ctx)
        ctx["served_by"] = {"provider": p, "model": config.provider(p)["model"]}
        return out
    except ProviderError as e:
        other = config.fallback()
        if not other:
            raise
        log.warning("ai provider %s failed (%s); trying %s", p, e, other)
        out = _call_one(other, list(first), system, ctx)
        ctx["served_by"] = {"provider": other, "model": config.provider(other)["model"], "after": f"{p}: {e}"}
        return out


def test_key(p: str, key: str | None = None, model: str | None = None) -> dict:
    """Check a key (the saved one, or a new one before saving) with the service itself.

    Claude: looks up the model (no tokens used).  Z.ai: a one-token request."""
    cfg = config.provider(p)
    key = key or cfg["key"]
    model = model or cfg["model"]
    if not key:
        return {"ok": False, "detail": "No key is set for this service."}
    if not model:
        return {"ok": False, "detail": "Choose a model first."}
    if p == "anthropic":
        import anthropic

        client = anthropic.Anthropic(api_key=key, timeout=20.0, max_retries=0)
        try:
            m = client.models.retrieve(model)
        except anthropic.AuthenticationError:
            return {"ok": False, "detail": "Anthropic did not accept this key."}
        except anthropic.PermissionDeniedError:
            return {"ok": False, "detail": f"This key may not use {model}."}
        except anthropic.NotFoundError:
            return {"ok": False, "detail": f"The key works, but Anthropic has no model called {model}."}
        except anthropic.RateLimitError:
            return {"ok": True, "detail": "Anthropic accepted the key (it is rate-limited just now)."}
        except anthropic.APIStatusError as e:
            return {"ok": False, "detail": f"Anthropic answered with error {e.status_code}."}
        except anthropic.APIConnectionError:
            return {"ok": False, "detail": "Anthropic could not be reached from the server."}
        return {"ok": True, "detail": f"Anthropic accepted the key; {m.display_name} is available."}
    if p == "zai":
        body = {
            "model": model,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
            "thinking": {"type": "disabled"},
        }
        try:
            r = httpx.post(
                BASE_URLS["zai"] + "/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json=body,
                timeout=30.0,
            )
        except httpx.HTTPError:
            return {"ok": False, "detail": "Z.ai could not be reached from the server."}
        if r.status_code == 200:
            return {"ok": True, "detail": f"Z.ai accepted the key; {model} answered."}
        if r.status_code in (401, 403):
            return {"ok": False, "detail": "Z.ai did not accept this key."}
        if r.status_code == 429:
            return {"ok": True, "detail": "Z.ai accepted the key (it is rate-limited just now)."}
        return {"ok": False, "detail": f"Z.ai answered with error {r.status_code} (check the model name)."}
    return {"ok": False, "detail": "This service is set in .env and cannot be checked here."}


# --------------------------------------------------------------------------------------
# Checking and answering
# --------------------------------------------------------------------------------------


def _directions(analyses: dict) -> list[dict]:
    out = []
    for r in analyses.values():
        if r["kind"] == "trend":
            names = [r["region"]["name"], r["variable"]["name"].split(" (")[0]]
            out.append({"names": names, "direction": r["stats"]["direction"]})
    return out


def verify(answer: dict, analyses: dict, lang: str) -> dict:
    cited = [a for a in answer.get("analysis_ids", []) if a in analyses] or list(analyses)
    allowed: list[float] = []
    for aid in cited:
        allowed += allowed_numbers(analyses[aid])
    text = f"{answer.get('headline', '')}\n{answer.get('explanation', '')}"
    res = check_text(text, allowed, _directions({a: analyses[a] for a in cited}), lang)
    return {
        "ok": res.ok and bool(cited),
        "unmatched_numbers": res.unmatched,
        "direction_errors": res.direction_errors,
        "numbers_checked": res.checked,
        "cited": cited,
    }


def _fallback_payload(analyses: dict, reason: str) -> dict:
    cards = [_public_card(r) for r in analyses.values()]
    return {
        "mode": "fallback",
        "reason": reason,
        "answer": None,
        "analyses": cards,
        "template_verdicts": [
            {"analysis_id": r["id"], **{k: r["verdict"][k] for k in ("headline", "sentences", "caveats")}}
            for r in analyses.values()
        ],
    }


def _public_card(r: dict) -> dict:
    """Card data for the page, straight from the stored analysis."""
    return {"analysis_id": r["id"], "kind": r["kind"], "card": _card(r)}


def _timing(ctx: dict, t0: float) -> dict:
    tm = ctx.get("timing", {"model_s": [], "tools": []})
    out = {
        "total_s": round(time.time() - t0, 1),
        "ai_calls": len(tm["model_s"]),
        "ai_s": round(sum(tm["model_s"]), 1),
        "per_call_s": tm["model_s"],
        "tools": tm["tools"],
    }
    log.info("ai timing %s", json.dumps(out))
    return out


def ask(question: str, lang: str, mode: str, history: list[dict], ip: str, progress=None) -> dict:
    reason = _gate(ip)
    if reason:
        return {"mode": "unavailable", "reason": reason, "answer": None, "analyses": []}
    ctx = {"lang": lang, "analyses": {}, "progress": progress}
    system = SYSTEM.format(lang=lang) + (TUTOR if mode == "tutor" else "")
    messages = []
    for h in history[-6:]:
        if h.get("role") in ("user", "assistant") and isinstance(h.get("content"), str):
            messages.append({"role": h["role"], "content": h["content"][:2000]})
    messages.append({"role": "user", "content": question})
    t0 = time.time()
    try:
        answer, tin, tout = _call(messages, system, ctx)
    except ProviderError as e:
        _record("failed")
        return _fallback_payload(
            ctx["analyses"], f"The AI service failed ({e}). Here are the computed results instead."
        )
    except Exception:  # noqa: BLE001
        log.exception("AI failure")
        _record("failed")
        return _fallback_payload(
            ctx["analyses"], "The AI service failed. Here are the computed results instead."
        )
    if not ctx["analyses"]:
        _record("fallback", tin, tout)
        return {
            "mode": "no_analysis",
            "reason": "The AI did not run any analysis, so it has nothing checked to say. Try naming a place and a variable.",
            "answer": None,
            "analyses": [],
            "suggestions": answer.get("follow_up_questions", [])[:3],
        }
    _emit(ctx, {"step": "check"})
    check = verify(answer, ctx["analyses"], lang)
    if not check["ok"]:
        _record("fallback", tin, tout)
        out = _fallback_payload(
            ctx["analyses"],
            "The AI's explanation did not match the computed numbers, so it is not shown. Here are the computed results.",
        )
        out["check"] = check
        out["timing"] = _timing(ctx, t0)
        return out
    _record("answered", tin, tout)
    return {
        "timing": _timing(ctx, t0),
        "tokens": {"input": tin, "output": tout},
        "mode": "answered",
        "answer": {k: answer.get(k) for k in ("headline", "explanation", "follow_up_questions")},
        "check": check,
        "analyses": [_public_card(ctx["analyses"][a]) for a in check["cited"]],
        "seconds": round(time.time() - t0, 1),
        "provider": ctx.get("served_by", {}).get("provider", _provider()),
        "model": ctx.get("served_by", {}).get("model", _model()),
    }


def explain(analysis_id: str, lang: str, ip: str) -> dict:
    with connect() as conn:
        rep = service.get_report(conn, analysis_id)
    if not rep:
        return {"mode": "error", "reason": "unknown analysis"}
    r = rep["result"]
    analyses = {r["id"]: r}
    reason = _gate(ip)
    if reason:
        return _fallback_payload(analyses, reason)
    ctx = {"lang": lang, "analyses": analyses}
    system = SYSTEM.format(lang=lang) + "\nThe analysis is already done: explain it. Do not call tools."
    q = f"Explain this result to a member of the public. Stored analysis: {json.dumps(_card(r), default=str)}"
    try:
        answer, tin, tout = _call([{"role": "user", "content": q}], system, ctx)
    except Exception as e:  # noqa: BLE001
        _record("failed")
        return _fallback_payload(analyses, f"The AI service failed ({e}). Here is the computed verdict.")
    answer["analysis_ids"] = [r["id"]]
    check = verify(answer, analyses, lang)
    if not check["ok"]:
        _record("fallback", tin, tout)
        out = _fallback_payload(
            analyses,
            "The AI's explanation did not match the computed numbers, so here is the computed verdict.",
        )
        out["check"] = check
        return out
    _record("answered", tin, tout)
    return {
        "mode": "answered",
        "answer": {k: answer.get(k) for k in ("headline", "explanation", "follow_up_questions")},
        "check": check,
        "analyses": [_public_card(r)],
    }


__all__ = ["ask", "explain", "status", "verify", "VARIABLES"]
