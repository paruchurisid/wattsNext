"""Ollama adapter tuned for Llama 3.2 3B. Configuration is read at call time."""
import json
import os
import socket
import urllib.error
import urllib.request

DEFAULT_MODEL = "llama3.2:3b"


class LocalProviderError(Exception):
    def __init__(self, message, category="unavailable"):
        super().__init__(message)
        self.category = category


def base_url():
    return os.environ.get("OLLAMA_BASE_URL", os.environ.get("OPENLLAMA_URL", "http://127.0.0.1:11434")).rstrip("/")


def model_name():
    return os.environ.get("OLLAMA_MODEL", os.environ.get("OPENLLAMA_MODEL", DEFAULT_MODEL))


def _request(path, body=None, timeout=3):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(base_url() + path, data=data,
        headers={"Content-Type": "application/json"}, method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
        if not isinstance(result, dict):
            raise LocalProviderError("Invalid response from Ollama", "invalid_response")
        if result.get("error"):
            raise LocalProviderError("Ollama could not complete the request")
        return result
    except urllib.error.HTTPError as exc:
        category = "model_missing" if exc.code == 404 else "unavailable"
        raise LocalProviderError("Local model is not installed" if exc.code == 404 else "Ollama request failed", category) from exc
    except (TimeoutError, socket.timeout) as exc:
        raise LocalProviderError("Local model timed out", "timeout") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise LocalProviderError("Cannot reach Ollama. Start Ollama and try again.") from exc
    except (ValueError, UnicodeError) as exc:
        raise LocalProviderError("Invalid response from Ollama", "invalid_response") from exc


def status():
    model = model_name()
    try:
        result = _request("/api/tags")
        names = [item.get("name") for item in result.get("models", []) if isinstance(item, dict)]
        installed = model in names or (":" not in model and model + ":latest" in names)
        return {"model": model, "connected": installed, "available_models": names,
                "error": None if installed else {"category": "model_missing", "message": f"Install {model} with ollama pull {model}."}}
    except LocalProviderError as exc:
        return {"model": model, "connected": False, "available_models": [],
                "error": {"category": exc.category, "message": str(exc)}}


def generate(prompt, timeout=None, *, system=None, history=None):
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    for turn in (history or [])[-4:]:
        role = "assistant" if turn.get("role") == "model" else turn.get("role")
        content = " ".join(part.get("text", "") for part in turn.get("parts", []) if isinstance(part, dict))
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content[:1200]})
    messages.append({"role": "user", "content": prompt})
    if timeout is None:
        try:
            timeout = max(1, min(120, float(os.environ.get("OLLAMA_TIMEOUT", "60"))))
        except ValueError:
            timeout = 60
    result = _request("/api/chat", {
        "model": model_name(), "stream": False, "keep_alive": "10m",
        "options": {"temperature": 0, "num_ctx": 4096, "num_predict": 180, "repeat_penalty": 1.1},
        "messages": messages,
    }, timeout=timeout)
    message = result.get("message")
    text = message.get("content") if isinstance(message, dict) else None
    if not isinstance(text, str) or not text.strip():
        raise LocalProviderError("Local model returned no text", "invalid_response")
    if result.get("done_reason") == "length":
        raise LocalProviderError("Local model response was cut short", "invalid_response")
    return text.strip()
