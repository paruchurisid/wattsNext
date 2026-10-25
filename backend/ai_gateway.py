import hashlib, time
from .validator import validate
from .audit_log import record

def deterministic_response(text, payload):
    values = []
    def walk(x):
        if isinstance(x, dict):
            for v in x.values(): walk(v)
        elif isinstance(x, (int, float)): values.append(x)
    walk(payload)
    check = validate(text, values)
    record(household_id=payload.get("household_id"), deterministic_input_hash=hashlib.sha256(repr(payload).encode()).hexdigest(), raw_llm_output=text, validation_passed=check["passed"], fallback_triggered=not check["passed"], latency_ms=0)
    return {"text": text if check["passed"] else "Offline mode — generated from deterministic rules. " + payload.get("fallback_text", "Please use the displayed estimate and safety guidance."), "validation": check, "fallback": not check["passed"]}
