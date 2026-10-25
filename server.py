"""
Watt'sNext server: routes, in-memory sessions, chat orchestration, provider
connection. Binds to 127.0.0.1 only. No API keys are ever logged or written
to disk — they live only in the in-memory SETTINGS dict for this process.
"""
import uuid
import os
from pathlib import Path
from datetime import datetime, timezone

import uvicorn
from starlette.applications import Starlette
from starlette.responses import JSONResponse, FileResponse
from starlette.routing import Route, Mount
from starlette.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from concierge import cases, chat, customer_services, gemini, tools, local_llm, knowledge
from backend import data_pipeline, risk_model, audit_log, restoration as restoration_engine, db, weather

def _load_env_file():
    for name in (".env.local", ".env"):
        path = Path(name)
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if "=" in line and not line.startswith("#"):
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip().strip('"'))
            break

_load_env_file()
_gemini_key = os.environ.get("GEMINI_API_KEY")
SETTINGS = {
    "api_key": _gemini_key,
    "model": os.environ.get("GEMINI_MODEL", "gemini-2.5-flash") if _gemini_key else None,
    "provider": os.environ.get("WATTSNEXT_PROVIDER", "local"),
    "offline_mode": False,
    "last_error": None,
}
SESSIONS = {}

DEFAULT_SCENARIO = {"access_blocked": False, "extra_crews": 0, "repairs_complete": False}


def _new_session(household_id):
    session_id = uuid.uuid4().hex
    SESSIONS[session_id] = {
        "household_id": household_id,
        "scenario": dict(DEFAULT_SCENARIO),
        "history": [],
        "previous_estimate": None,
        "events": [],
        "triggered_alerts": {},
        "busy": False,
        "declared_needs": {},
        "knowledge": None,
    }
    return session_id


def _log_event(session, event_type, detail):
    session["events"].append({
        "type": event_type,
        "detail": detail,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })


def _record_alerts(session, alerts_result):
    for preview in alerts_result.get("message_previews", []):
        if preview["type"] not in session["triggered_alerts"]:
            session["triggered_alerts"][preview["type"]] = preview
            _log_event(session, "alert_previewed", {"alert_type": preview["type"], "message": preview["message"]})


def _log_estimate_change(session, before, after):
    if before.get("fallback", {}).get("fallback") or after.get("fallback", {}).get("fallback"):
        return
    if before["low_hours"]["value"] == after["low_hours"]["value"] and before["high_hours"]["value"] == after["high_hours"]["value"]:
        return
    _log_event(session, "estimate_changed", {
        "before": [before["low_hours"]["value"], before["high_hours"]["value"]],
        "after": [after["low_hours"]["value"], after["high_hours"]["value"]],
    })


async def list_cities(request):
    return JSONResponse({"cities": cases.list_cities()})


async def list_households(request):
    households = [
        {"household_id": h["household_id"], "display_name": h["display_name"], "city": h["city"]}
        for h in cases.list_households()
    ]
    return JSONResponse({"households": households})


async def create_session(request):
    body = await _json_object(request)
    if body is None:
        return JSONResponse({"error": "expected a JSON object"}, status_code=400)
    household_id = body.get("household_id")
    if not isinstance(household_id, str) or cases.get_household(household_id) is None:
        return JSONResponse({"error": "unknown household_id"}, status_code=400)
    session_id = _new_session(household_id)
    try:
        snapshot = await run_in_threadpool(_household_knowledge, SESSIONS[session_id])
    except Exception:
        SESSIONS.pop(session_id, None)
        return JSONResponse({"error": "We could not prepare this household's information. Please try again."}, status_code=503)
    return JSONResponse({"session_id": session_id, "household_id": household_id,
                         "chat_ready": True, "knowledge_revision": snapshot["revision"], "knowledge": snapshot})


def _session_or_404(session_id):
    return SESSIONS.get(session_id) if isinstance(session_id, str) else None


async def _json_object(request):
    try:
        body = await request.json()
    except ValueError:
        return None
    return body if isinstance(body, dict) else None


async def chat_endpoint(request):
    try:
        body = await request.json()
    except ValueError:
        return JSONResponse({"error": "invalid JSON"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"error": "expected an object"}, status_code=400)
    session_id = body.get("session_id")
    if not isinstance(session_id, str) or not isinstance(body.get("message"), str):
        return JSONResponse({"error": "session_id and message must be strings"}, status_code=400)
    message = body["message"].strip()
    session = _session_or_404(session_id)
    if session is None:
        return JSONResponse({"error": "unknown session_id"}, status_code=404)
    if not message:
        return JSONResponse({"error": "empty message"}, status_code=400)
    if len(message) > 2000:
        return JSONResponse({"error": "Please keep messages under 2,000 characters."}, status_code=400)
    if session["busy"]:
        return JSONResponse({"error": "A reply is still being prepared. Please wait."}, status_code=409)
    session["busy"] = True
    try:
        reply = await run_in_threadpool(_chat_reply, message, session, dict(SETTINGS))
    finally:
        session["busy"] = False

    session["history"].append({"role": "user", "parts": [{"text": message}]})
    if reply.get("text"):
        session["history"].append({"role": "model", "parts": [{"text": reply["text"]}]})
    session["history"] = session["history"][-12:]
    restoration = reply.get("cards", {}).get("restoration")
    if restoration and not restoration.get("fallback", {}).get("fallback"):
        if session["previous_estimate"] is not None:
            _log_estimate_change(session, {
                "fallback": {"fallback": False},
                "low_hours": {"value": session["previous_estimate"]["low_hours"]},
                "high_hours": {"value": session["previous_estimate"]["high_hours"]},
            }, restoration)
        session["previous_estimate"] = {
            "low_hours": restoration["low_hours"]["value"],
            "high_hours": restoration["high_hours"]["value"],
        }
    if "alerts" in reply.get("cards", {}):
        _record_alerts(session, reply["cards"]["alerts"])
    return JSONResponse(reply)


def _chat_reply(message, session, settings):
    session["declared_needs"].update(chat.declared_needs_update(message))
    if chat.needs_live_data_refusal(message):
        snapshot = _household_knowledge(session)
        return {"text": chat.OFFICIAL_LINKS_TEXT, "cards": {}, "fallback": False, "offline": False,
                "knowledge_revision": snapshot["revision"], "knowledge": snapshot}
    action = chat.scenario_action(message)
    before = None
    if action:
        before = tools.get_restoration_estimate(session["household_id"], **session["scenario"])
        WHATIF_ACTIONS[action](session["scenario"])
        _log_event(session, "whatif_applied", {"action": action})
    snapshot = _household_knowledge(session)
    if settings["offline_mode"]:
        reply = chat.offline_reply(message, session["household_id"], session["scenario"], session["history"], session["declared_needs"], snapshot)
    elif settings["provider"] == "local" or not settings["api_key"] or not settings["model"]:
        reply = chat.local_reply(message, session["household_id"], session["scenario"], session["history"], session["declared_needs"], snapshot)
    else:
        try:
            reply = chat.online_reply(
                settings["api_key"], settings["model"], message,
                session["household_id"], session["scenario"], session["history"],
                session["declared_needs"],
                snapshot,
            )
        except gemini.ProviderError as e:
            SETTINGS["last_error"] = {"category": e.category, "message": e.message}
            # Customer-service continuity: Gemini is optional. If it fails,
            # render the same deterministic answer through the local model.
            reply = chat.local_reply(message, session["household_id"], session["scenario"], session["history"], session["declared_needs"], snapshot)
            reply["provider_fallback"] = {"from": "gemini", "category": e.category}

    latest = _household_knowledge(session)
    if latest["revision"] != snapshot["revision"]:
        snapshot = latest
        reply = chat.offline_reply(message, session["household_id"], session["scenario"], [], session["declared_needs"], snapshot)
        reply["context_refreshed"] = True
        reply["text"] = "The household information changed while I was answering. Here are the updated facts. " + reply["text"]

    if action:
        after = tools.get_restoration_estimate(session["household_id"], **session["scenario"])
        reply["scenario_change"] = {"action": action, "before": before, "after": after, "scenario": dict(session["scenario"])}
        reply["text"] = "Example updated. " + reply["text"]
        if not after.get("fallback", {}).get("fallback"):
            previous = {"low_hours": before["low_hours"]["value"], "high_hours": before["high_hours"]["value"]}
            reply["cards"]["alerts"] = tools.get_alert_info(session["household_id"], **session["scenario"], previous_estimate=previous, declared_needs=session["declared_needs"])
            if session["previous_estimate"] is None:
                session["previous_estimate"] = previous
    reply["knowledge_revision"] = snapshot["revision"]
    reply["knowledge"] = snapshot
    return reply


def _household_knowledge(session):
    cached = session.get("knowledge")
    needs = {**cases.get_household(session["household_id"])["declared_needs"], **session["declared_needs"]}
    if (cached is None or cached["scenario"] != session["scenario"] or
            cached["household"]["declared_needs"] != needs or
            cached.get("source_revision") != knowledge.source_revision(session["household_id"])):
        cached = knowledge.build(session["household_id"], session["scenario"], session["declared_needs"])
        session["knowledge"] = cached
        # Older replies must not influence answers after a data or scenario change.
        session["history"] = []
    return cached


async def wiki_endpoint(request):
    session = _session_or_404(request.query_params.get("session_id"))
    if session is None:
        return JSONResponse({"error": "unknown session_id"}, status_code=404)
    return JSONResponse(await run_in_threadpool(_household_knowledge, session))


WHATIF_ACTIONS = {
    "block_access": lambda s: s.update(access_blocked=True),
    "clear_access": lambda s: s.update(access_blocked=False),
    "add_crews": lambda s: s.update(extra_crews=s["extra_crews"] + 2),
    "complete_repairs": lambda s: s.update(repairs_complete=True),
    "reset": lambda s: s.update(DEFAULT_SCENARIO),
}


async def whatif_endpoint(request):
    body = await _json_object(request)
    if body is None:
        return JSONResponse({"error": "expected a JSON object"}, status_code=400)
    session_id = body.get("session_id")
    action = body.get("action")
    session = _session_or_404(session_id)
    if session is None:
        return JSONResponse({"error": "unknown session_id"}, status_code=404)
    if session["busy"]:
        return JSONResponse({"error": "Wait for the current reply before changing the scenario."}, status_code=409)
    if not isinstance(action, str) or action not in WHATIF_ACTIONS:
        return JSONResponse({"error": "unknown action"}, status_code=400)

    session["busy"] = True
    try:
        return JSONResponse(await run_in_threadpool(_apply_whatif, session, action))
    finally:
        session["busy"] = False


def _apply_whatif(session, action):

    household_id = session["household_id"]
    before = tools.get_restoration_estimate(household_id, **session["scenario"])

    WHATIF_ACTIONS[action](session["scenario"])
    _log_event(session, "whatif_applied", {"action": action})

    after = tools.get_restoration_estimate(household_id, **session["scenario"])
    risk = tools.get_risk(household_id, session["scenario"]["repairs_complete"], session["scenario"]["access_blocked"])
    prep = tools.get_prep_guidance(household_id, session["scenario"]["repairs_complete"], session["declared_needs"])
    alerts = tools.get_alert_info(household_id, **session["scenario"], previous_estimate=session["previous_estimate"], declared_needs=session["declared_needs"])

    _log_estimate_change(session, before, after)
    _record_alerts(session, alerts)

    session["previous_estimate"] = {
        "low_hours": after.get("low_hours", {}).get("value"),
        "high_hours": after.get("high_hours", {}).get("value"),
    } if not after.get("fallback", {}).get("fallback") else None

    snapshot = _household_knowledge(session)
    return {
        "scenario": session["scenario"],
        "before": before,
        "after": after,
        "risk": risk,
        "prep": prep,
        "alerts": alerts,
        "chat_ready": True,
        "knowledge_revision": snapshot["revision"],
        "knowledge": snapshot,
    }


async def dashboard_endpoint(request):
    session_id = request.query_params.get("session_id")
    session = _session_or_404(session_id)
    if session is None:
        return JSONResponse({"error": "unknown session_id"}, status_code=404)

    household_id = session["household_id"]
    scenario = session["scenario"]
    risk = tools.get_risk(household_id, scenario["repairs_complete"], scenario["access_blocked"])
    restoration = tools.get_restoration_estimate(household_id, **scenario)
    replay_payload = restoration_engine.estimate(cases.case_for_household(household_id), **scenario)
    timeline = tools.get_job_timeline(household_id, extra_crews=scenario["extra_crews"], repairs_complete=scenario["repairs_complete"])

    alerts = []
    for alert_type in customer_services.ALERT_TYPES:
        triggered = session["triggered_alerts"].get(alert_type)
        alerts.append({
            "type": alert_type,
            "timing": customer_services.ALERT_TIMINGS[alert_type],
            "triggered": triggered is not None,
            "message": triggered["message"] if triggered else None,
        })

    return JSONResponse({
        "scenario": scenario,
        "risk": risk,
        "restoration": restoration,
        "monte_carlo": replay_payload["monte_carlo"],
        "topology": replay_payload["topology"],
        "previous_estimate": session["previous_estimate"],
        "timeline": timeline,
        "alerts": alerts,
        "events": list(reversed(session["events"])),
    })


async def get_settings(request):
    local = await run_in_threadpool(local_llm.status) if SETTINGS["provider"] == "local" and not SETTINGS["offline_mode"] else None
    return JSONResponse({
        "model": local_llm.model_name() if SETTINGS["provider"] == "local" else SETTINGS["model"],
        "provider": SETTINGS["provider"],
        "offline_mode": SETTINGS["offline_mode"],
        "connected": (local["connected"] if local else bool(SETTINGS["api_key"] and SETTINGS["model"])) and not SETTINGS["offline_mode"],
        "last_error": local["error"] if local else SETTINGS["last_error"],
        "local": local,
    })


async def update_settings(request):
    body = await _json_object(request)
    if body is None:
        return JSONResponse({"error": "expected a JSON object"}, status_code=400)
    if ("provider" in body and body["provider"] not in ("local", "gemini") or
            "offline_mode" in body and not isinstance(body["offline_mode"], bool) or
            "api_key" in body and not isinstance(body["api_key"], str)):
        return JSONResponse({"error": "invalid settings"}, status_code=400)
    updated = dict(SETTINGS)

    provider = body.get("provider")
    if provider in ("local", "gemini"):
        updated["provider"] = provider
        updated["last_error"] = None

    if "offline_mode" in body:
        updated["offline_mode"] = body["offline_mode"]

    api_key = body.get("api_key")
    if api_key:
        try:
            model = await run_in_threadpool(gemini.pin_model, api_key)
            updated["api_key"] = api_key
            updated["model"] = model
            updated["provider"] = "gemini"
            updated["last_error"] = None
            updated["offline_mode"] = False
        except gemini.ProviderError as e:
            SETTINGS["last_error"] = {"category": e.category, "message": e.message}
            return JSONResponse({
                "error": "provider_error",
                "category": e.category,
                "offer_offline": True,
            }, status_code=502)

    SETTINGS.update(updated)
    return await get_settings(request)


async def index(request):
    return FileResponse("static/index.html")

async def data_quality(request):
    report = data_pipeline.quality_report()
    report["neon"] = db.table_counts()
    return JSONResponse(report)

async def model_card(request):
    return JSONResponse({"name":"Watt'sNext deterministic replay", "intended_use":"customer education and storm replay", "not_intended_for":"live dispatch or SCADA control", "calibration": risk_model.backtest(), "constraints":["no inferred vulnerability", "no utility-confirmed claims", "Gemini cannot alter numbers"]})

async def governance_audit(request):
    return JSONResponse({"entries": audit_log.read_all()})

async def api_docs(request):
    return JSONResponse({"openapi":"3.0.0", "info":{"title":"Watt'sNext API","version":"1.0"}, "paths":{
        "/api/governance/data-quality":{"get":{}}, "/api/governance/model-card":{"get":{}},
        "/api/governance/audit-log":{"get":{}}, "/api/replay":{"get":{}}, "/api/whatif":{"post":{}}, "/api/chat":{"post":{}}}})

async def database_health(request):
    return JSONResponse(db.ping())

async def readiness(request):
    result = db.ping()
    return JSONResponse({"ready": result.get("connected", False), "database": result}, status_code=200 if result.get("connected") else 503)

async def import_readiness(request):
    return JSONResponse(db.import_readiness())

async def weather_alerts(request):
    return JSONResponse(await run_in_threadpool(weather.active_alerts))

async def replay(request):
    session = _session_or_404(request.query_params.get("session_id"))
    if session is None: return JSONResponse({"error":"unknown session_id"}, status_code=404)
    case = cases.case_for_household(session["household_id"])
    return JSONResponse(restoration_engine.estimate(case, **session["scenario"]))


app = Starlette(routes=[
    Route("/", index),
    Route("/api/cities", list_cities),
    Route("/api/households", list_households),
    Route("/api/session", create_session, methods=["POST"]),
    Route("/api/chat", chat_endpoint, methods=["POST"]),
    Route("/api/whatif", whatif_endpoint, methods=["POST"]),
    Route("/api/dashboard", dashboard_endpoint),
    Route("/api/wiki", wiki_endpoint),
    Route("/api/settings", get_settings, methods=["GET"]),
    Route("/api/settings", update_settings, methods=["POST"]),
    Route("/api/governance/data-quality", data_quality),
    Route("/api/governance/model-card", model_card),
    Route("/api/governance/audit-log", governance_audit),
    Route("/api/docs", api_docs),
    Route("/api/health/database", database_health),
    Route("/api/health/ready", readiness),
    Route("/api/governance/import-readiness", import_readiness),
    Route("/api/weather/alerts", weather_alerts),
    Route("/api/replay", replay),
    Mount("/static", StaticFiles(directory="static"), name="static"),
])


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
