"""Bounded HTTP smoke checks without language-model calls."""
import argparse
import json
import os
import time
import urllib.request


def check(base_url, require_database=False, attempts=1):
    headers = {"Content-Type": "application/json"}
    if os.environ.get("VERCEL_AUTOMATION_BYPASS_SECRET"):
        headers["x-vercel-protection-bypass"] = os.environ["VERCEL_AUTOMATION_BYPASS_SECRET"]

    def request(path, payload=None):
        data = json.dumps(payload).encode() if payload is not None else None
        with urllib.request.urlopen(urllib.request.Request(base_url.rstrip("/") + path, data=data, headers=headers), timeout=15) as response:
            raw = response.read().decode()
        return json.loads(raw) if path.startswith("/api/") else raw

    for attempt in range(attempts):
        try:
            assert "view-wiki-btn" in request("/")
            assert "info" in request("/api/docs")
            if require_database:
                assert request("/api/health/ready")["ready"] is True
            households = request("/api/households")
            items = households["households"] if isinstance(households, dict) else households
            assert items
            session = request("/api/session", {"household_id": items[0]["household_id"]})
            assert session["chat_ready"] is True
            assert session["knowledge"]["chat_context"]["ready"] is True
            wiki = request("/api/wiki?session_id=" + session["session_id"])
            assert wiki["revision"] == session["knowledge_revision"]
            assert wiki["faqs"]
            print("Homepage, API, household loading, and prepared Wiki passed")
            return
        except (AssertionError, KeyError, ValueError, OSError):
            if attempt == attempts - 1:
                raise RuntimeError("Smoke check failed; inspect deployment logs") from None
            time.sleep(2)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--require-database", action="store_true")
    parser.add_argument("--attempts", type=int, default=1)
    args = parser.parse_args()
    check(args.url, args.require_database, args.attempts)
