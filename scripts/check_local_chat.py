"""Repeatable live smoke check for the configured local Ollama model."""
import argparse
import json
import time
from concierge import chat, local_llm


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quick", action="store_true", help="Run only the primary demo question")
    args = parser.parse_args()
    print(json.dumps(local_llm.status()))
    scenarios = [
        ("baseline", "h1", "Will I lose power and for how long?", {}),
        ("medical", "h2", "What should I do to prepare?", {}),
        ("blocked", "h1", "How long will repairs take?", {"access_blocked": True}),
        ("complete", "h1", "When will power be back on?", {"repairs_complete": True}),
        ("alerts", "h1", "Do I qualify for outage alerts?", {}),
        ("follow_up", "h1", "Why is that?", {}),
    ]
    history = []
    success = True
    for label, household, message, updates in scenarios[:1] if args.quick else scenarios:
        scenario = {"access_blocked": False, "extra_crews": 0, "repairs_complete": False, **updates}
        started = time.monotonic()
        result = chat.local_reply(message, household, scenario, history if label == "follow_up" else [])
        print(json.dumps({"case": label, "seconds": round(time.monotonic() - started, 2),
                          "model": result.get("local_model"), "fallback": result.get("local_fallback", False),
                          "error": result.get("local_error"), "text": result["text"]}, ensure_ascii=True), flush=True)
        success = success and not result.get("local_fallback", False)
        if label == "baseline":
            history = [{"role": "user", "parts": [{"text": message}]},
                       {"role": "model", "parts": [{"text": result["text"]}]}]
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
