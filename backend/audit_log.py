import json, pathlib
from datetime import datetime, timezone

PATH = pathlib.Path("data/audit.jsonl")
def record(**entry):
    PATH.parent.mkdir(exist_ok=True)
    payload = {"timestamp": datetime.now(timezone.utc).isoformat(), **entry}
    with PATH.open("a", encoding="utf-8") as f: f.write(json.dumps(payload) + "\n")
    return payload
def read_all():
    if not PATH.exists(): return []
    return [json.loads(x) for x in PATH.read_text(encoding="utf-8").splitlines() if x.strip()]
