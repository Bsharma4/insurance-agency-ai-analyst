"""Minimal LLM client for any OpenAI-compatible chat completions API.

Works with Google Gemini (free tier), Groq, OpenRouter, or a local Ollama server:
only LLM_BASE_URL, LLM_API_KEY and LLM_MODEL in .env change.
Uses only the standard library (urllib), so there is nothing to install.
"""

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

RETRY_STATUS_CODES = {429, 500, 502, 503}   # rate limited / temporarily overloaded
MAX_ATTEMPTS = 4                            # 1 try + 3 retries, waits of 2s, 4s, 8s


def load_env(path: Path = ROOT / ".env") -> None:
    """Read KEY=VALUE lines from .env into os.environ (real env vars win)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def chat(messages: list[dict], temperature: float = 0.0, timeout: int = 60) -> str:
    """Send a chat request and return the model's text reply."""
    load_env()
    base_url = os.environ.get("LLM_BASE_URL", "").rstrip("/")
    api_key = os.environ.get("LLM_API_KEY", "")
    model = os.environ.get("LLM_MODEL", "")
    if not (base_url and model):
        raise RuntimeError("Set LLM_BASE_URL and LLM_MODEL in .env (see .env.example).")

    body = json.dumps({"model": model, "messages": messages, "temperature": temperature}).encode()
    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
    )
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.load(response)
            break
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:500]
            if e.code in RETRY_STATUS_CODES and attempt < MAX_ATTEMPTS:
                wait = 2 ** attempt
                print(f"  (LLM API busy: HTTP {e.code}, retry {attempt}/{MAX_ATTEMPTS - 1} in {wait}s)")
                time.sleep(wait)
                continue
            raise RuntimeError(f"LLM API returned HTTP {e.code}: {detail}") from e

    return payload["choices"][0]["message"]["content"]


def parse_json_reply(text: str) -> dict:
    """Extract the JSON object from a reply, tolerating ```json fences."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"Model did not return JSON:\n{text[:500]}")
    return json.loads(text[start : end + 1])
