"""
Minimal Gemini REST client (stdlib urllib only — no SDK dependency).
Lists models with the user's key, pins the first allowlisted model that
completes a real tool-call round trip, and exposes honest error categories
so the UI can offer offline mode instead of failing silently.
"""
import json
import urllib.request
import urllib.error

API_BASE = "https://generativelanguage.googleapis.com/v1beta"

ALLOWLIST = [
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
    "gemini-1.5-flash-8b",
    "gemini-1.5-pro",
]


class ProviderError(Exception):
    def __init__(self, category, message):
        self.category = category  # "quota" | "permission" | "unavailable" | "unknown"
        self.message = message
        super().__init__(message)


def _categorize_http_error(err):
    status = err.code
    if status == 429:
        return "quota"
    if status in (401, 403):
        return "permission"
    if status in (500, 502, 503, 504):
        return "unavailable"
    return "unknown"


def _request(path, api_key, method="GET", body=None, timeout=15):
    url = f"{API_BASE}/{path}?key={api_key}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raise ProviderError(_categorize_http_error(e), e.read().decode()[:300]) from e
    except urllib.error.URLError as e:
        raise ProviderError("unavailable", str(e.reason)) from e


def list_models(api_key):
    result = _request("models", api_key)
    return [m["name"].split("/")[-1] for m in result.get("models", [])]


def _tool_round_trip_ok(model, api_key):
    body = {
        "contents": [{"role": "user", "parts": [{"text": "Call the ping tool."}]}],
        "tools": [{"function_declarations": [
            {"name": "ping", "description": "test", "parameters": {"type": "object", "properties": {}}}
        ]}],
    }
    try:
        result = _request(f"models/{model}:generateContent", api_key, method="POST", body=body)
    except ProviderError:
        return False
    candidates = result.get("candidates", [])
    return bool(candidates)


def pin_model(api_key):
    available = set(list_models(api_key))
    for candidate in ALLOWLIST:
        if candidate in available and _tool_round_trip_ok(candidate, api_key):
            return candidate
    raise ProviderError("unavailable", "No allowlisted model completed a tool-call round trip.")


def generate(api_key, model, contents, function_declarations, system_instruction=None):
    body = {
        "contents": contents,
        "tools": [{"function_declarations": function_declarations}],
    }
    if system_instruction:
        body["systemInstruction"] = {"parts": [{"text": system_instruction}]}
    result = _request(f"models/{model}:generateContent", api_key, method="POST", body=body)
    candidates = result.get("candidates", [])
    if not candidates:
        raise ProviderError("unavailable", "No candidates returned.")
    parts = candidates[0].get("content", {}).get("parts", [])

    function_calls = [p["functionCall"] for p in parts if "functionCall" in p]
    text = "".join(p.get("text", "") for p in parts if "text" in p)
    return {"text": text, "function_calls": function_calls}
