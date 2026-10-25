"""
Chat orchestration: routes a user message to either the Gemini tool-calling
loop or the offline deterministic templates. Both paths produce the same
shape of response so the frontend never has to special-case the provider.

Safety guard runs first, regardless of mode: questions needing live or
account data never reach a tool call.
"""
import re

from . import tools, gemini, local_llm, knowledge
from backend.validator import validate, NUMBER

NO_LIVE_DATA_PATTERNS = [
    r"\bshelter\b", r"\bcredit\b", r"\bcompensation\b", r"\brebate\b",
    r"\bweather\b", r"\bforecast\b", r"\bcrew (location|position)\b",
    r"\blive (outage|map|feed)\b", r"\bis.*open\b", r"\bcurrent outage\b",
]

OFFICIAL_LINKS_TEXT = (
    "I don't have live or account data for that. For current outage maps and account-specific "
    "information, check the official Appalachian Power outage center (appalachianpower.com/outages) "
    "or, for shelter and relief needs, the American Red Cross (redcross.org)."
)

SYSTEM_INSTRUCTION = (
    "You are Watt'sNext, AEP's storm outage concierge. You never invent numbers — call the provided "
    "tools and explain their output. Never claim live weather, outage, or crew-position data. Never "
    "infer health information from context; only use what the customer explicitly declares. Answers to "
    "questions should use everyday words, short sentences, and at most 80 words. Answer the question first. "
    "Explain only the detail the customer asked about. Follow-up answers should be 1-3 sentences. Ask at most one "
    "follow-up question. If a tool reports fallback=true, say plainly that a reliable estimate isn't "
    "available for this location and give general safety guidance plus the official outage link."
)


def needs_live_data_refusal(message):
    lowered = message.lower()
    return any(re.search(p, lowered) for p in NO_LIVE_DATA_PATTERNS)


def scenario_action(message):
    """Recognize the same explicit replay controls offered by the UI."""
    lowered = message.lower().strip()
    if not re.match(r"(?:what if\b|simulate\b|assume\b|mark\b|add\b|reset\b|start over\b)", lowered):
        return None
    if re.search(r"\b(reset|start over)\b", lowered):
        return "reset"
    if re.search(r"\b(?:access|road)\b.*\b(clear|cleared|open|unblocked|not blocked)\b", lowered):
        return "clear_access"
    if re.search(r"\b(?:access|road)\b.*\bblocked\b", lowered):
        return "block_access"
    if re.search(r"\b(?:2|two)\s+(?:more |extra )?(?:repair )?(?:crews|teams)\b", lowered):
        return "add_crews"
    if re.search(r"\brepairs?\b.*\b(finish|finished|complete|completed)\b", lowered):
        return "complete_repairs"
    return None


def _word_count(text):
    return len(text.split())


def classify_intent(message):
    lowered = message.lower()
    if any(k in lowered for k in ("confidence interval", "upstream", "power-line terms", "what is a transformer", "what does transformer", "what is a crew", "what is an assumption", "what is a power pole", "how does a transformer")):
        return "glossary"
    if any(k in lowered for k in ("confidence", "how sure", "how certain", "less certain", "certainty", "why uncertain", "trust the estimate")):
        return "confidence"
    if any(k in lowered for k in ("real-time", "real time", "where does", "where did", "data come", "source", "real data", "live data")):
        return "sources"
    if any(k in lowered for k in ("what changes", "why don", "why doesn", "extra teams", "more crews help", "more teams help")):
        return "scenarios"
    if any(k in lowered for k in ("crew", "team")) and "how many" in lowered:
        return "scenarios"
    if any(k in lowered for k in ("information are you using", "household needs", "what do you know about", "what have i told")):
        return "household"
    if any(k in lowered for k in ("p10", "p50", "p90", "median", "percentile", "statistics", "probability", "percentage", "shorter", "middle time", "longer time", "these numbers", "chance", "different times", "numbers differ", "times differ")):
        return "statistics"
    if any(k in lowered for k in ("alert", "qualify", "notify", "notification", "send me", "send messages", "text message", "send updates")):
        return "alerts"
    if any(k in lowered for k in ("prepare", "get ready", "should i do", "safety", "medical device", "cpap", "oxygen concentrator", "generator", "downed", "flashlight", "food", "medicine", "battery", "batteries", "water")):
        return "prep"

    has_restoration = any(k in lowered for k in ("how long", "restoration", "repair", "fix", "back on", "back up", "when", "how much time"))
    has_risk = any(k in lowered for k in ("lose power", "risk", "going to lose", "will i"))
    if has_restoration and has_risk:
        return "risk_restoration"
    if has_restoration:
        return "restoration"
    if has_risk:
        return "risk"
    return "overview"

def is_greeting(message):
    cleaned = re.sub(r"[^a-z ]", "", message.lower()).strip()
    return cleaned in {"hi", "hello", "hey", "hiya", "good morning", "good afternoon", "good evening", "thanks", "thank you"}

def small_talk_reply(message):
    cleaned = re.sub(r"[^a-z ]", "", message.lower()).strip()
    if cleaned in {"thanks", "thank you"}:
        return "You’re welcome. If you need anything else, I can help with outage risk, restoration timing, preparation, or alerts."
    if cleaned in {"good morning", "good afternoon", "good evening"}:
        return "Hello — I’m Watt’sNext. How can I help with your power service today?"
    if cleaned in {"who are you", "what are you", "what can you do", "help", "can you help me"}:
        return "I’m Watt’sNext. I can explain this example for your household, show how long repairs could take, and help you get ready. I use the same information as Wiki. I cannot check live outages or your power-company account."
    if cleaned in {"bye", "goodbye", "see you", "thats all", "that's all"}:
        return "Take care. If the power goes out, stay away from downed lines and use the official Appalachian Power outage center for live status."
    return None


def declared_needs_update(message):
    """Only explicit first-person declarations affect this conversation's needs."""
    lowered = message.lower()
    medical = r"(?:medical device|oxygen concentrator|cpap|ventilator|powered medical equipment)"
    if re.search(r"\bi (?:do not|don't|no longer) (?:use|need|rely on|have) (?:a |an )?" + medical, lowered):
        return {"medical_device": False}
    if re.search(r"\b(?:i (?:use|need|have|rely on)|my) (?:a |an )?(?:power[- ]dependent )?" + medical, lowered):
        return {"medical_device": True}
    return {}


def _offline_answer(intent, household_id, scenario, declared_needs=None, knowledge_snapshot=None):
    cards = {}
    if intent in {"confidence", "sources", "scenarios", "glossary", "household"}:
        snapshot = knowledge_snapshot or knowledge.build(household_id, scenario, declared_needs)
        answer = next(item["answer"] for item in snapshot["faqs"] if item["id"] == intent)
        result = {"text": answer, "cards": {}, "fallback": False, "wiki_topic": intent}
        if intent == "confidence" and snapshot["risk"].get("confidence"):
            result["confidence_level"] = snapshot["risk"]["confidence"]["value"]
        return result
    fallback = tools.get_fallback_status(household_id)
    if fallback["fallback"]:
        return {
            "text": f"{fallback['reason']} Follow general storm safety guidance and check the official "
                    "Appalachian Power outage map (appalachianpower.com/outages) for live information.",
            "cards": {},
            "fallback": True,
        }

    if intent in ("risk", "risk_restoration", "overview"):
        cards["risk"] = tools.get_risk(household_id, scenario["repairs_complete"], scenario["access_blocked"])
    if intent in ("restoration", "risk_restoration", "overview"):
        cards["restoration"] = tools.get_restoration_estimate(household_id, **scenario)
    if intent in ("prep", "restoration", "risk_restoration", "overview"):
        cards["prep"] = tools.get_prep_guidance(household_id, scenario["repairs_complete"], declared_needs)
    if intent in ("alerts", "overview"):
        cards["alerts"] = tools.get_alert_info(household_id, **scenario, declared_needs=declared_needs)
    if knowledge_snapshot:
        cards = {key: knowledge_snapshot[key] for key in cards}
    if intent == "statistics":
        snapshot = knowledge_snapshot or knowledge.build(household_id, scenario, declared_needs)
        cards["statistics"] = snapshot["statistics"]
        cards["risk"] = snapshot["risk"]

    text = _render_offline_text(intent, cards)
    return {"text": text, "cards": cards, "fallback": False}


def _render_offline_text(intent, cards):
    parts = []
    if "statistics" in cards:
        stats = cards["statistics"]
        mc = stats["restoration_simulation"]
        if mc:
            parts.append(f"The computer examples give a shorter repair time of {mc['p10']} hours, a middle time of {mc['p50']} hours, and a longer time of {mc['p90']} hours.")
        parts.append(stats["note"])
    if "risk" in cards:
        r = cards["risk"]
        parts.append(
            f"This example shows {r['risk_band']['value']} risk of losing power, with {r['confidence']['value']} confidence. {r['risk_reason']}"
        )
    if "restoration" in cards:
        e = cards["restoration"]
        if e["reference_effort_hours"]["value"] == 0.0:
            parts.append("Repairs are complete in this example. If your power is still off, check your breakers, then report it to your power company.")
        else:
            parts.append(
                f"Repairs could take {e['low_hours']['value']}-{e['high_hours']['value']} hours. "
                "These times are not confirmed by your power company."
            )
            if e["access_blocked"]["value"]:
                parts.append("The example includes an extra delay for a blocked road.")
            if e["crew_count"]["value"] > 1:
                parts.append("Extra teams can work on separate repairs at the same time, but cannot split a single repair.")
    if "prep" in cards:
        all_actions = cards["prep"]["actions"]
        if intent == "prep":
            shown = all_actions
        else:
            safety = [a for a in all_actions if a.startswith("SAFETY:")]
            other = [a for a in all_actions if not a.startswith("SAFETY:")]
            shown = safety + other[: max(1, 2 - len(safety))]
        parts.append("What you can do: " + " ".join(shown))
    if "alerts" in cards:
        a = cards["alerts"]
        if a["eligible"]:
            channel = {"sms": "text messages", "email": "email"}.get(a["channel"], a["channel"])
            parts.append(f"Example updates are turned on for this household by {channel}.")
        else:
            parts.append("Example updates are turned off for this household.")
        parts.append("This app shows example messages only. It does not send them. Manage real updates through your power company's account settings.")
    if not parts:
        parts.append("Ask me whether you'll lose power, how long repairs could take, how to prepare, or whether you qualify for alerts.")
    return " ".join(parts)


def _contextual_intent(message, history):
    intent = classify_intent(message)
    # Resolve short follow-ups against the last substantive customer question.
    if intent == "overview" and re.search(r"\b(why|that|it|explain|mean|sure|again|more)\b", message.lower()):
        for turn in reversed(history or []):
            if turn.get("role") == "user":
                previous = " ".join(p.get("text", "") for p in turn.get("parts", []))
                previous_intent = classify_intent(previous)
                if previous_intent != "overview":
                    return previous_intent
    return intent


def _is_short_followup(message, history):
    return bool(history and classify_intent(message) == "overview" and
                re.search(r"\b(why|that|it|explain|mean|sure|again|more)\b", message.lower()) and len(message.split()) <= 12)


def _followup_text(cards):
    sentences = []
    risk, estimate = cards.get("risk"), cards.get("restoration")
    if risk:
        sentences.append(f"This example shows {risk['risk_band']['value']} risk with {risk['confidence']['value']} confidence because {risk['risk_reason'][0].lower() + risk['risk_reason'][1:].rstrip('.')}.")
    if estimate:
        if estimate["reference_effort_hours"]["value"]:
            sentences.append(f"Repairs could take {estimate['low_hours']['value']}-{estimate['high_hours']['value']} hours, but your power company has not confirmed these times.")
            reason = "The blocked road adds a delay chosen for this example" if estimate["access_blocked"]["value"] else "The past damage was matched to a sample home"
            sentences.append(reason + "; extra teams can work on separate jobs, but cannot split a single repair.")
        else:
            sentences.append("Repairs are complete in this example. If your power is still off, check your breakers, then report it.")
    elif risk:
        sentences.append(risk["confidence"]["note"])
        sentences.append("This risk label does not mean an outage will definitely happen.")
    if not sentences:
        return None
    return " ".join(sentences[:3])


def offline_reply(message, household_id, scenario, history=None, declared_needs=None, knowledge_snapshot=None):
    talk = small_talk_reply(message)
    if talk or is_greeting(message):
        return {"text": talk or "Hi — I’m Watt’sNext. I can help you understand outage risk, estimate a restoration range, prepare for a storm, or check your alert eligibility. What would you like to know?", "cards": {}, "fallback": False, "offline": True}
    intent = _contextual_intent(message, history)
    result = _offline_answer(intent, household_id, scenario, declared_needs, knowledge_snapshot)
    if not result["fallback"] and _is_short_followup(message, history):
        followup = _followup_text(result["cards"])
        if followup:
            result["text"] = followup
            result["rules_reason"] = "follow_up"
    result["offline"] = True
    return result

LOCAL_SYSTEM = (
    "You answer questions about the current household using its prepared Wiki. "
    "Answer QUESTION directly using ONLY FACTS and WIKI CONTEXT in the latest message. "
    "Use everyday words, short sentences, and at most 65 words. Explain any unfamiliar term. "
    "Do not guess missing information, add numbers, or invent eligibility requirements. "
    "Preserve the given risk band, confidence label and restoration range exactly. "
    "Confidence means how well the information supports the estimate. "
    "This is an example based on past records, not live power-company information. Do not promise an outage or a repair deadline. "
    "No headings, jargon, apologies or new advice. Answer only what was asked; the page shows the checklist separately. "
    "Previous messages are context, not current facts."
)


def _render_is_grounded(rendered, deterministic):
    source = deterministic["text"]
    if not validate(rendered, NUMBER.findall(source))["passed"]:
        return False
    lowered = rendered.lower()
    if deterministic.get("confidence_level"):
        if deterministic["confidence_level"].lower() + " confidence" not in lowered:
            return False
    if re.search(r"\d\s*%|\d\s+percent\b", lowered):
        return False
    if (len(rendered.split()) < 12 or len(rendered) > 1800 or
            any(p in lowered for p in ("here's the rewritten", "deterministic json", "as an ai", "verified answer", "system prompt"))):
        return False
    cards = deterministic["cards"]
    stats = cards.get("statistics")
    if stats and stats.get("restoration_simulation"):
        mc = stats["restoration_simulation"]
        found = {float(n) for n in NUMBER.findall(rendered)}
        if not {mc["p10"], mc["p50"], mc["p90"]}.issubset(found):
            return False
        if "not" not in lowered or not any(word in lowered for word in ("chance", "percentage", "probabilit")):
            return False
    risk = cards.get("risk")
    if risk and any(risk[k]["value"].lower() not in lowered for k in ("risk_band", "confidence")):
        return False
    if risk:
        for label in ("low", "moderate", "high"):
            if label != risk["risk_band"]["value"].lower() and re.search(r"\b" + label + r"\s+(?:outage )?risk\b|\brisk (?:is |level is )?" + label + r"\b", lowered):
                return False
        for label in ("low", "medium", "high"):
            if label != risk["confidence"]["value"].lower() and re.search(r"\b" + label + r"\s+confidence\b", lowered):
                return False
    estimate = cards.get("restoration")
    if estimate:
        if estimate["reference_effort_hours"]["value"]:
            found = {float(n) for n in NUMBER.findall(rendered)}
            if not {estimate["low_hours"]["value"], estimate["high_hours"]["value"]}.issubset(found):
                return False
            if "not confirmed" not in lowered:
                return False
        elif not any(word in lowered for word in ("simulation", "example")) or "report" not in lowered:
            return False
    if "SAFETY:" in source and not all(p in lowered for p in ("provider", "backup", "not a substitute")):
        return False
    if any(p in lowered for p in ("guaranteed", "priority restoration", "currently experiencing", "we have dispatched", "live data shows", "cascade failure", "secondary failures", "not actual utility records", "not fully understood", "damage is significant")):
        return False
    return True


def _attach_verified_guidance(rendered, deterministic):
    """Critical qualifications and safety instructions never depend on a small model."""
    cards = deterministic["cards"]
    if cards.get("statistics") and "chance of losing power" not in rendered.lower():
        rendered += " " + cards["statistics"]["note"]
    estimate = cards.get("restoration")
    if estimate and estimate["reference_effort_hours"]["value"] and "not confirmed" not in rendered.lower():
        rendered += " These times are not confirmed by your power company."
    if cards.get("risk"):
        risk = cards["risk"]
        if any(risk[k]["value"].lower() not in rendered.lower() for k in ("risk_band", "confidence")):
            rendered += f" This example shows {risk['risk_band']['value']} risk with {risk['confidence']['value']} confidence."
        if "example" not in rendered.lower():
            rendered += " This is an example, not a report of a current outage at your home."
    if cards.get("prep"):
        actions = cards["prep"]["actions"]
        safety = [a for a in actions if a.startswith("SAFETY:")]
        if safety and "not a substitute" not in rendered.lower():
            rendered += " " + " ".join(safety)
    if estimate and not estimate["reference_effort_hours"]["value"]:
        rendered += " Repairs are complete in this example. If your power is still off, check your breakers, then report it."
    return rendered


def local_reply(message, household_id, scenario, history=None, declared_needs=None, knowledge_snapshot=None, *, prepare=False):
    """The local model explains Python's answer; cards and numbers stay authoritative."""
    knowledge_snapshot = knowledge_snapshot or knowledge.build(household_id, scenario, declared_needs)
    deterministic = offline_reply(message, household_id, scenario, history, declared_needs, knowledge_snapshot)
    if deterministic.get("fallback"):
        deterministic["offline"] = True
        return deterministic
    # Completed-repair status is a safety-critical state transition, not a prose task.
    if scenario["repairs_complete"] and "restoration" in deterministic["cards"]:
        deterministic["rules_reason"] = "repairs_complete"
        return deterministic
    if _contextual_intent(message, history) == "prep":
        deterministic["rules_reason"] = "safety_guidance"
        return deterministic
    facts = {k: v for k, v in deterministic["cards"].items() if k != "prep"}
    fact_text = _render_offline_text(_contextual_intent(message, history), facts) if facts else deterministic["text"]
    prompt = ("QUESTION: " + message + "\nFACTS (computed household Wiki):\n" + fact_text +
              "\nWIKI CONTEXT:\n" + knowledge.context_text(knowledge_snapshot, _contextual_intent(message, history), message))
    if prepare:
        return {"local_request": {"system": LOCAL_SYSTEM, "prompt": prompt, "history": (history or [])[-4:]},
                "local_expected": deterministic}
    try:
        rendered = local_llm.generate(prompt, system=LOCAL_SYSTEM, history=history)
        return finish_local_reply(rendered, deterministic, local_llm.model_name())
    except local_llm.LocalProviderError as exc:
        deterministic["offline"] = True
        deterministic["local_fallback"] = True
        deterministic["local_error"] = {"category": exc.category, "message": str(exc)}
        return deterministic


def finish_local_reply(rendered, deterministic, model):
    """Validate browser-local inference against the server's computed facts."""
    rendered = _attach_verified_guidance(rendered, deterministic)
    if not _render_is_grounded(rendered, deterministic):
        return {**deterministic, "offline": True, "local_fallback": True,
                "local_error": {"category": "validation", "message": "The model answer did not preserve the household facts."}}
    return {"text": rendered, "cards": deterministic["cards"], "fallback": False,
            "offline": False, "local_model": model}


def online_reply(api_key, model, message, household_id, scenario, history, declared_needs=None, knowledge_snapshot=None):
    contents = list(history) + [{"role": "user", "parts": [{"text": message}]}]
    instruction = SYSTEM_INSTRUCTION
    if knowledge_snapshot:
        instruction += "\nCurrent household Wiki:\n" + knowledge.context_text(knowledge_snapshot, _contextual_intent(message, history), message)
    response = gemini.generate(api_key, model, contents, tools.FUNCTION_DECLARATIONS, instruction)

    cards = {}
    if response["function_calls"]:
        function_response_parts = []
        for call in response["function_calls"]:
            name = call["name"]
            declaration = next((d for d in tools.FUNCTION_DECLARATIONS if d["name"] == name), None)
            if declaration is None:
                raise gemini.ProviderError("unavailable", "The provider requested an unsupported tool.")
            # Household and scenario belong to the session, never the model.
            args = {"household_id": household_id}
            for key in declaration["parameters"]["properties"]:
                if key in scenario:
                    args[key] = scenario[key]
            if name in ("get_prep_guidance", "get_alert_info"):
                args["declared_needs"] = declared_needs
            result = tools.DISPATCH[name](**args)
            card_key = {"get_risk": "risk", "get_restoration_estimate": "restoration", "get_prep_guidance": "prep", "get_alert_info": "alerts"}[name]
            cards[card_key] = result
            function_response_parts.append({
                "functionResponse": {"name": name, "response": result}
            })
        contents.append({"role": "model", "parts": [{"functionCall": c} for c in response["function_calls"]]})
        contents.append({"role": "user", "parts": function_response_parts})
        response = gemini.generate(api_key, model, contents, tools.FUNCTION_DECLARATIONS, instruction)
    if not response["text"] or response["function_calls"]:
        raise gemini.ProviderError("unavailable", "The provider did not finish its answer.")
    if "restoration" in cards and "prep" not in cards:
        cards["prep"] = tools.get_prep_guidance(household_id, scenario["repairs_complete"], declared_needs)
    return {"text": response["text"], "cards": cards, "fallback": False, "offline": False, "gemini_model": model}
