"""Piece 32.0: Compendium AI assistant — provider layer.

A tiny, dependency-free client for the two chat providers Vixinman has access to:
Anthropic (Claude) and Google (Gemini). Kept in pure stdlib on purpose — Compendium
ships as a frozen PyInstaller exe, so adding SDKs would bloat the bundle and
complicate packaging. Both providers are reduced to the same shape:

    ask(provider, api_key, model, system, user_message) -> answer text

The request/response *builders* and *parsers* are separated from the network
call so they can be unit-tested without hitting the internet (the app is
offline-capable; the assistant is the one online-only feature).
"""

import json
import urllib.request
import urllib.error

# Selectable Claude models (label -> id). Sonnet is the sensible default for
# internal Q&A — cheaper than Opus, plenty capable for "what's the status of…".
CLAUDE_MODELS = [
    ("Claude Sonnet (balanced, recommended)", "claude-sonnet-5"),
    ("Claude Opus (most capable, pricier)", "claude-opus-5"),
    ("Claude Haiku (fastest, cheapest)", "claude-haiku-4-5"),
]
CLAUDE_MODEL_IDS = [m for _label, m in CLAUDE_MODELS]
CLAUDE_DEFAULT_MODEL = "claude-sonnet-5"

# Gemini model IDs move around as Google ships new versions, so this is a plain
# editable setting rather than a fixed list — default to a widely-available one.
GEMINI_DEFAULT_MODEL = "gemini-2.0-flash"

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
GEMINI_URL_TMPL = ("https://generativelanguage.googleapis.com/v1beta/models/"
                   "{model}:generateContent")

REQUEST_TIMEOUT = 45  # seconds — a single interactive question


class AssistantError(Exception):
    """A user-facing failure from the assistant (bad key, network, provider)."""


# ----------------------------------------------------------------------------
# Claude (Anthropic Messages API)
# ----------------------------------------------------------------------------
def build_claude_request(api_key, model, system, user_message, max_tokens=1024):
    """Return (url, headers, body_dict) for one Claude Messages API call."""
    headers = {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    body = {
        "model": model or CLAUDE_DEFAULT_MODEL,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user_message}],
    }
    return ANTHROPIC_URL, headers, body


def parse_claude_response(data):
    """Pull the assistant's text out of a Claude Messages API response."""
    if data.get("type") == "error":
        raise AssistantError(_provider_error_text(data))
    parts = [b.get("text", "") for b in data.get("content", [])
             if b.get("type") == "text"]
    text = "".join(parts).strip()
    if not text:
        raise AssistantError("Claude returned an empty response.")
    return text


# ----------------------------------------------------------------------------
# Gemini (Google Generative Language API)
# ----------------------------------------------------------------------------
def build_gemini_request(api_key, model, system, user_message):
    """Return (url, headers, body_dict) for one Gemini generateContent call."""
    url = GEMINI_URL_TMPL.format(model=model or GEMINI_DEFAULT_MODEL)
    # The key rides as a header (x-goog-api-key) rather than a query string so it
    # never lands in logs or the URL.
    headers = {"content-type": "application/json", "x-goog-api-key": api_key}
    body = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user_message}]}],
    }
    return url, headers, body


def parse_gemini_response(data):
    """Pull the assistant's text out of a Gemini generateContent response."""
    if "error" in data:
        raise AssistantError(_provider_error_text(data["error"]))
    candidates = data.get("candidates") or []
    if not candidates:
        # Often a safety block — surface the reason if present.
        fb = (data.get("promptFeedback") or {}).get("blockReason")
        raise AssistantError(
            f"Gemini declined to answer{f' ({fb})' if fb else ''}.")
    parts = (candidates[0].get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts).strip()
    if not text:
        raise AssistantError("Gemini returned an empty response.")
    return text


# ----------------------------------------------------------------------------
# Shared plumbing
# ----------------------------------------------------------------------------
def _provider_error_text(err):
    if isinstance(err, dict):
        msg = err.get("message") or (err.get("error") or {}).get("message")
        if msg:
            return str(msg)
    return "The AI provider returned an error."


def _post_json(url, headers, body, timeout=REQUEST_TIMEOUT):
    """POST a JSON body and return the decoded JSON response. Raises
    AssistantError with a friendly message on any transport/HTTP failure."""
    raw = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=raw, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = _provider_error_text(json.loads(e.read().decode("utf-8")))
        except Exception:
            detail = e.reason or ""
        if e.code in (401, 403):
            raise AssistantError(
                "The AI provider rejected the API key — check it in AI settings.")
        if e.code == 429:
            raise AssistantError(
                "The AI provider is rate-limiting requests — try again shortly.")
        raise AssistantError(f"AI provider error ({e.code}): {detail}".strip())
    except urllib.error.URLError as e:
        raise AssistantError(
            "Couldn't reach the AI provider — check the internet connection. "
            f"({getattr(e, 'reason', e)})")
    except Exception as e:  # JSON decode, ssl, etc.
        raise AssistantError(f"Unexpected error talking to the AI provider: {e}")


def ask(provider, api_key, model, system, user_message):
    """Ask one question of the chosen provider and return the answer text.
    `provider` is 'claude' or 'gemini'. Raises AssistantError on any problem."""
    if not (api_key or "").strip():
        raise AssistantError(
            "No API key is set for this provider — add one in AI settings.")
    if provider == "gemini":
        url, headers, body = build_gemini_request(api_key, model, system, user_message)
        return parse_gemini_response(_post_json(url, headers, body))
    # default: claude
    url, headers, body = build_claude_request(api_key, model, system, user_message)
    return parse_claude_response(_post_json(url, headers, body))


# ----------------------------------------------------------------------------
# Piece 32.1: tool-using agent loop — lets the model look data up live via a set
# of read-only tools, instead of only reading a fixed snapshot.
#
# A tool is a dict: {"name", "description", "parameters" (JSON-schema object),
# "run" (callable(args_dict) -> str)}. The caller (app.py) defines the tools and
# their permission-scoped implementations; this module only drives the provider
# request/response loop for each of Claude and Gemini.
# ----------------------------------------------------------------------------
MAX_AGENT_STEPS = 6  # tool round-trips before we force a final answer


def _dispatch(registry, name, args):
    """Run one tool by name; never raise — return an error string the model can
    read and recover from."""
    tool = registry.get(name)
    if tool is None:
        return f"Error: no such tool '{name}'."
    try:
        out = tool["run"](args or {})
        return str(out) if out is not None else ""
    except Exception as e:  # a tool bug must not crash the whole answer
        return f"Error running {name}: {e}"


def run_agent(provider, api_key, model, system, user_message, tools,
              max_steps=MAX_AGENT_STEPS):
    """Answer a question, letting the model call read-only tools as needed.
    Returns the final answer text. Raises AssistantError on transport/provider
    failure. Falls back to a plain (tool-less) call if `tools` is empty."""
    if not (api_key or "").strip():
        raise AssistantError(
            "No API key is set for this provider — add one in AI settings.")
    if not tools:
        return ask(provider, api_key, model, system, user_message)
    registry = {t["name"]: t for t in tools}
    if provider == "gemini":
        return _gemini_agent(api_key, model, system, user_message, tools,
                             registry, max_steps)
    return _claude_agent(api_key, model, system, user_message, tools,
                         registry, max_steps)


def _claude_agent(api_key, model, system, user_message, tools, registry, max_steps):
    tool_defs = [{"name": t["name"], "description": t["description"],
                  "input_schema": t["parameters"]} for t in tools]
    headers = {"x-api-key": api_key, "anthropic-version": ANTHROPIC_VERSION,
               "content-type": "application/json"}
    messages = [{"role": "user", "content": user_message}]
    for _ in range(max_steps):
        body = {"model": model or CLAUDE_DEFAULT_MODEL, "max_tokens": 1024,
                "system": system, "messages": messages, "tools": tool_defs}
        data = _post_json(ANTHROPIC_URL, headers, body)
        if data.get("type") == "error":
            raise AssistantError(_provider_error_text(data))
        content = data.get("content", [])
        tool_uses = [b for b in content if b.get("type") == "tool_use"]
        if not tool_uses:  # final answer
            return parse_claude_response(data)
        messages.append({"role": "assistant", "content": content})
        results = []
        for tu in tool_uses:
            out = _dispatch(registry, tu.get("name"), tu.get("input"))
            results.append({"type": "tool_result", "tool_use_id": tu.get("id"),
                            "content": out})
        messages.append({"role": "user", "content": results})
    # Ran out of steps — ask for a final answer with tools withheld.
    body = {"model": model or CLAUDE_DEFAULT_MODEL, "max_tokens": 1024,
            "system": system, "messages": messages}
    return parse_claude_response(_post_json(ANTHROPIC_URL, headers, body))


def _gemini_agent(api_key, model, system, user_message, tools, registry, max_steps):
    decls = []
    for t in tools:
        d = {"name": t["name"], "description": t["description"]}
        # Gemini rejects an empty parameters object — include it only when there
        # are properties to describe.
        if (t["parameters"].get("properties") or {}):
            d["parameters"] = t["parameters"]
        decls.append(d)
    url = GEMINI_URL_TMPL.format(model=model or GEMINI_DEFAULT_MODEL)
    headers = {"content-type": "application/json", "x-goog-api-key": api_key}
    gem_tools = [{"function_declarations": decls}]
    contents = [{"role": "user", "parts": [{"text": user_message}]}]
    for _ in range(max_steps):
        body = {"system_instruction": {"parts": [{"text": system}]},
                "contents": contents, "tools": gem_tools}
        data = _post_json(url, headers, body)
        if "error" in data:
            raise AssistantError(_provider_error_text(data["error"]))
        cand = (data.get("candidates") or [{}])[0]
        parts = (cand.get("content") or {}).get("parts") or []
        calls = [p["functionCall"] for p in parts if p.get("functionCall")]
        if not calls:  # final answer
            return parse_gemini_response(data)
        contents.append({"role": "model", "parts": parts})
        resp_parts = []
        for call in calls:
            out = _dispatch(registry, call.get("name"), call.get("args"))
            resp_parts.append({"functionResponse": {
                "name": call.get("name"), "response": {"result": out}}})
        contents.append({"role": "user", "parts": resp_parts})
    # Ran out of steps — force a final answer with tools withheld.
    body = {"system_instruction": {"parts": [{"text": system}]}, "contents": contents}
    return parse_gemini_response(_post_json(url, headers, body))
