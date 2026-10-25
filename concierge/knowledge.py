"""Prepared, plain-language household facts shared by Wiki and chat."""
import hashlib
import json
import re
from . import cases, tools
from backend import restoration, risk_model

ASSET_NAMES = {"transformer": "transformer", "primary": "power line", "primary_wire": "power line", "pole": "power pole"}


def source_revision(household_id):
    source = {"household": cases.get_household(household_id), "case": cases.case_for_household(household_id)}
    return hashlib.sha256(json.dumps(source, sort_keys=True, default=str).encode()).hexdigest()[:16]


def build(household_id, scenario, declared_needs=None):
    household = cases.get_household(household_id)
    case = cases.case_for_household(household_id)
    risk = tools.get_risk(household_id, scenario["repairs_complete"], scenario["access_blocked"])
    estimate = tools.get_restoration_estimate(household_id, **scenario)
    prep = tools.get_prep_guidance(household_id, scenario["repairs_complete"], declared_needs)
    alerts = tools.get_alert_info(household_id, **scenario, declared_needs=declared_needs)
    fallback = tools.get_fallback_status(household_id)
    model = risk_model.risk_payload(case, scenario["repairs_complete"]) if not fallback["fallback"] else None
    simulation = restoration.estimate(case, **scenario) if not fallback["fallback"] else None
    snapshot = {
        "household": {"household_id": household_id, "display_name": household["display_name"], "city": household["city"],
                      "declared_needs": {**household["declared_needs"], **(declared_needs or {})}},
        "source_revision": source_revision(household_id),
        "scenario": dict(scenario), "fallback": fallback,
        "risk": risk, "restoration": estimate, "prep": prep, "alerts": alerts,
        "statistics": {"risk_model": model, "restoration_simulation": simulation["monte_carlo"] if simulation else None,
                       "note": "These are possible repair times from computer examples. The main repair estimate allows for a wider range of delays, so the numbers can differ. They do not tell you your chance of losing power. We cannot give a reliable outage percentage. Your power company has not confirmed these times."},
        "timeline": tools.get_job_timeline(household_id, scenario["extra_crews"], scenario["repairs_complete"]),
        "topology": simulation["topology"] if simulation else [],
    }
    snapshot["faqs"] = _faqs(snapshot)
    # Prepare the complete scenario-specific reference before the session is ready.
    # This is model context, not weight training or a provider-side shared memory.
    snapshot["chat_context"] = {
        "scope": _scope(snapshot),
        "documents": [{"id": item["id"], "question": item["question"], "answer": item["answer"]} for item in snapshot["faqs"]],
        "ready": True,
    }
    snapshot["revision"] = hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()[:16]
    return snapshot


def _scope(data):
    household = data["household"]
    return (f"Current household: {household['display_name']}, {household['city']}. "
            "Use only this household and this example. This is not a live power-company report. "
            f"Repairs complete in this example: {data['scenario']['repairs_complete']}. "
            f"Access blocked in this example: {data['scenario']['access_blocked']}. "
            f"Extra repair teams: {data['scenario']['extra_crews']}.")


def _faqs(data):
    fallback = data["fallback"]
    if fallback["fallback"]:
        risk_answer = restoration_answer = fallback["reason"]
    else:
        risk, estimate = data["risk"], data["restoration"]
        risk_answer = (f"This example shows {risk['risk_band']['value']} risk of a power outage. "
                       + risk["risk_reason"] + " It does not mean an outage will definitely happen.")
        restoration_answer = ("Repairs are marked complete in this example. If your power is still off, check your breakers, then report it to your power company."
            if estimate["reference_effort_hours"]["value"] == 0 else
            f"Repairs could take {estimate['low_hours']['value']}-{estimate['high_hours']['value']} hours in this example. "
            "Your power company has not confirmed these times. "
            "The estimate uses the damage in the example, typical repair work, available teams, and whether they can reach the site.")
    alerts = data["alerts"]
    channel = {"sms": "text messages", "email": "email"}.get(alerts.get("channel"), "messages")
    alert_answer = (f"This household has example notifications turned on for {channel}. "
                    if alerts.get("eligible") else "This household has example notifications turned off. ")
    alert_answer += "The examples show warnings, repair updates, and a message when work is done. This app does not send messages. Use your power company's account settings to manage real notifications."
    if alerts.get("fallback", {}).get("fallback"):
        alert_answer = "We do not have enough information to show notification options for this household. Check your power-company account to manage real notifications."
    mc = data["statistics"]["restoration_simulation"]
    stats_answer = data["statistics"]["note"]
    if mc:
        stats_answer = (f"The computer examples give a shorter repair time of {mc['p10']} hours, a middle time of {mc['p50']} hours, "
                        f"and a longer time of {mc['p90']} hours. The middle time sits halfway through the test results. "
                        "The shorter and longer times show how much repairs could vary. " + stats_answer)
    needs = data["household"]["declared_needs"]
    needs_text = []
    if needs.get("power_bank"): needs_text.append("a power bank is available")
    if needs.get("needs_phone_for_work"): needs_text.append("a phone is needed for work")
    if needs.get("medical_device"): needs_text.append("a medical device needs electricity")
    household_answer = (f"You are viewing {data['household']['display_name']} in {data['household']['city']}. " +
                        ("You have told us: " + "; ".join(needs_text) + "." if needs_text else "No extra needs have been shared.") +
                        " These details help choose the safety tips shown here. They do not change repair priority.")
    team_count = data["restoration"].get("crew_count", {}).get("value")
    team_text = f"This example uses {team_count} repair team{'s' if team_count != 1 else ''}. " if team_count is not None else ""
    return [
        {"id": "risk", "question": "Could I lose power?", "answer": risk_answer},
        {"id": "restoration", "question": "When could my power come back?", "answer": restoration_answer},
        {"id": "prep", "question": "What should I do now?", "answer": " ".join(data["prep"]["actions"])},
        {"id": "alerts", "question": "Will this app send me updates?", "answer": alert_answer},
        {"id": "statistics", "question": "What do the shorter, middle, and longer times mean?", "answer": stats_answer},
        {"id": "confidence", "question": "How sure are these estimates?", "answer": (
            f"We have {data['risk']['confidence']['value'].lower()} confidence in this estimate. " + data["risk"]["confidence"]["note"]
            if data["risk"].get("confidence") else fallback.get("reason"))},
        {"id": "scenarios", "question": "What changes when I try a different example?", "answer": team_text + "A blocked road adds an estimated delay. Extra teams can work on separate repairs at the same time, but cannot split a single repair between teams. Marking repairs complete ends the repair work in this example. Reset starts the original example again. Wiki and chat both update when you make a change."},
        {"id": "household", "question": "What information are you using for my household?", "answer": household_answer},
        {"id": "sources", "question": "Is this real-time information?", "answer": "No. This is an example based on past damage and repair records from AEP. We matched that damage to a sample household to show how repairs could affect it. We do not have live power-outage reports, team locations, shelter hours, or your utility account. Ask explains the same household information shown in Wiki."},
        {"id": "glossary", "question": "What do the power-line terms mean?", "answer": "An upstream path means the power lines and equipment that bring electricity to your home. A transformer changes electricity to a voltage homes can use. A repair crew is a team that fixes damaged equipment. An assumption is a detail we chose for the example because we do not have a confirmed measurement."},
        {"id": "live", "question": "Where can I check what is happening right now?", "answer": "For current outages, visit the official Appalachian Power outage center at https://appalachianpower.com/outages. For shelter and relief information, visit the American Red Cross at https://redcross.org."},
    ]


def context_text(snapshot, intent, message=""):
    """Retrieve relevant documents from the already-prepared household Wiki."""
    relevant = {
        "risk": {"risk", "confidence"}, "restoration": {"restoration", "confidence"},
        "risk_restoration": {"risk", "restoration", "confidence"},
        "overview": {"risk", "restoration", "sources"}, "statistics": {"statistics"},
    }.get(intent, {intent})
    documents = snapshot["chat_context"]["documents"]
    words = set(re.findall(r"[a-z]{4,}", message.lower())) - {"what", "this", "that", "with", "have", "does", "would", "could", "about", "please", "explain"}
    ranked = sorted(documents, key=lambda d: len(words & set(re.findall(r"[a-z]{4,}", (d["question"] + " " + d["answer"]).lower()))), reverse=True)
    if message and ranked:
        best = ranked[0]
        if words & set(re.findall(r"[a-z]{4,}", (best["question"] + " " + best["answer"]).lower())):
            relevant = relevant | {best["id"]}
    selected = [f"{item['question']} {item['answer']}" for item in documents if item["id"] in relevant]
    return snapshot["chat_context"]["scope"] + "\n" + "\n".join(selected)
