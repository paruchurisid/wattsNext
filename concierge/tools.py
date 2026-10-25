"""
Tools exposed to the language model. The model may only call these — it
never computes a number itself. Every numeric field is wrapped with an
evidence tag: source_data, assumption, model_estimate, or not_available.
"""
from . import cases, engine, customer_services

SOURCE_DATA = "source_data"
ASSUMPTION = "assumption"
MODEL_ESTIMATE = "model_estimate"
NOT_AVAILABLE = "not_available"


def _tag(value, evidence, note=None):
    return {"value": value, "evidence": evidence, "note": note}


def get_fallback_status(household_id):
    household = cases.get_household(household_id)
    case = cases.case_for_household(household_id)
    return engine.check_fallback(case) if household else {"fallback": True, "reason": "Unknown household."}


def get_risk(household_id, repairs_complete=False, access_blocked=False):
    household = cases.get_household(household_id)
    case = cases.case_for_household(household_id)
    fallback = engine.check_fallback(case)
    if fallback["fallback"]:
        return {"fallback": fallback}

    risk = engine.risk_band(case, repairs_complete=repairs_complete)
    conf = engine.confidence(case, access_blocked=access_blocked)
    return {
        "fallback": {"fallback": False, "reason": None},
        "city": household["city"],
        "risk_band": _tag(risk["band"], MODEL_ESTIMATE, "This risk label is for this example. It does not give an exact chance of an outage."),
        "risk_reason": risk["reason"],
        "confidence": _tag(conf["level"], MODEL_ESTIMATE, conf["reason"]),
        "storm_setting": _tag(case["storm_setting"], SOURCE_DATA),
        "confirmed_by_utility": _tag(None, NOT_AVAILABLE, "Your power company has not confirmed this example's estimates."),
    }


def get_restoration_estimate(household_id, access_blocked=False, extra_crews=0, repairs_complete=False):
    household = cases.get_household(household_id)
    case = cases.case_for_household(household_id)
    fallback = engine.check_fallback(case)
    if fallback["fallback"]:
        return {"fallback": fallback}

    estimate = engine.restoration_effort(
        case, access_blocked=access_blocked, extra_crews=extra_crews, repairs_complete=repairs_complete
    )
    conf = engine.confidence(case, access_blocked=access_blocked)

    return {
        "fallback": {"fallback": False, "reason": None},
        "low_hours": _tag(estimate["low_hours"], MODEL_ESTIMATE, "The shorter end of the estimated repair time. Actual repairs could take less or more time."),
        "high_hours": _tag(estimate["high_hours"], MODEL_ESTIMATE, "The longer end of the estimated repair time. Actual repairs could take less or more time."),
        "reference_effort_hours": _tag(estimate["reference_effort_hours"], MODEL_ESTIMATE),
        "access_blocked": _tag(access_blocked, ASSUMPTION, "We add 3 hours in the example when a road is blocked. This is not a measured delay."),
        "crew_count": _tag(estimate["crew_count"], ASSUMPTION, "The example starts with 1 repair team. You can add more teams to see what changes."),
        "damage_items": [
            {
                "asset_type": _tag(d["asset_type"], SOURCE_DATA),
                "quantity": _tag(d["quantity"], ASSUMPTION, "We chose this amount of damaged equipment for the sample home."),
                "repaired": _tag(d.get("repaired", True), SOURCE_DATA),
            }
            for d in case["damage_items"]
        ],
        "confidence": _tag(conf["level"], MODEL_ESTIMATE, conf["reason"]),
        "confirmed_by_utility": _tag(None, NOT_AVAILABLE, "Your power company has not confirmed these repair times."),
    }


def get_prep_guidance(household_id, repairs_complete=False, declared_needs=None):
    household = cases.get_household(household_id)
    if household and declared_needs:
        household = {**household, "declared_needs": {**household["declared_needs"], **declared_needs}}
    case = cases.case_for_household(household_id)
    fallback = engine.check_fallback(case)
    if fallback["fallback"]:
        return {
            "fallback": fallback,
            "actions": [
                "We can't give a reliable estimate for this location.",
                "Follow general storm safety guidance: charge devices, avoid downed lines, have water and food on hand.",
                "Check the official Appalachian Power outage map for live information.",
            ],
        }

    risk = engine.risk_band(case, repairs_complete=repairs_complete)
    actions = customer_services.prep_guidance(household, risk)
    if repairs_complete:
        actions = [
            "If your power is still out, check your breakers, then report the outage to the utility.",
            "Stay away from damaged or downed power lines even after repairs are marked complete.",
            "Recharge essential devices and review your supplies for future interruptions.",
        ] + [a for a in actions if a.startswith("SAFETY:")]
    return {"fallback": {"fallback": False, "reason": None}, "actions": actions}


def get_job_timeline(household_id, extra_crews=0, repairs_complete=False):
    case = cases.case_for_household(household_id)
    fallback = engine.check_fallback(case)
    if fallback["fallback"]:
        return {"fallback": fallback, "jobs": []}

    timeline = engine.job_timeline(case, crew_count=1 + extra_crews, repairs_complete=repairs_complete)
    return {
        "fallback": {"fallback": False, "reason": None},
        "jobs": [
            {
                "crew": j["crew"],
                "label": _tag(j["label"], SOURCE_DATA),
                "duration_hours": _tag(j["duration_hours"], MODEL_ESTIMATE),
                "status": j["status"],
            }
            for j in timeline
        ],
    }


def get_alert_info(household_id, access_blocked=False, extra_crews=0, repairs_complete=False, previous_estimate=None, declared_needs=None):
    household = cases.get_household(household_id)
    if household and declared_needs:
        household = {**household, "declared_needs": {**household["declared_needs"], **declared_needs}}
    case = cases.case_for_household(household_id)
    fallback = engine.check_fallback(case)
    if fallback["fallback"]:
        return {"fallback": fallback}

    estimate = engine.restoration_effort(
        case, access_blocked=access_blocked, extra_crews=extra_crews, repairs_complete=repairs_complete
    )
    eligibility = customer_services.alert_eligibility(household)
    triggers = customer_services.escalation_triggers(household)
    previews = customer_services.build_alert_previews(household, case, estimate, previous_estimate)

    return {
        "fallback": {"fallback": False, "reason": None},
        "eligible": eligibility["eligible"],
        "channel": eligibility["channel"],
        "reason": eligibility["reason"],
        "escalation_triggers": triggers,
        "message_previews": previews,
    }


FUNCTION_DECLARATIONS = [
    {
        "name": "get_risk",
        "description": "Get the outage risk band and confidence for a household.",
        "parameters": {
            "type": "object",
            "properties": {
                "household_id": {"type": "string"},
                "repairs_complete": {"type": "boolean"},
                "access_blocked": {"type": "boolean"},
            },
            "required": ["household_id"],
        },
    },
    {
        "name": "get_restoration_estimate",
        "description": "Get the restoration time range (hours) for a household, as a scenario range.",
        "parameters": {
            "type": "object",
            "properties": {
                "household_id": {"type": "string"},
                "access_blocked": {"type": "boolean"},
                "extra_crews": {"type": "integer"},
                "repairs_complete": {"type": "boolean"},
            },
            "required": ["household_id"],
        },
    },
    {
        "name": "get_prep_guidance",
        "description": "Get preparation and safety actions tailored to a household's declared needs.",
        "parameters": {
            "type": "object",
            "properties": {
                "household_id": {"type": "string"},
                "repairs_complete": {"type": "boolean"},
            },
            "required": ["household_id"],
        },
    },
    {
        "name": "get_alert_info",
        "description": "Get alert eligibility, channel, escalation triggers, and message previews for a household.",
        "parameters": {
            "type": "object",
            "properties": {
                "household_id": {"type": "string"},
                "access_blocked": {"type": "boolean"},
                "extra_crews": {"type": "integer"},
                "repairs_complete": {"type": "boolean"},
            },
            "required": ["household_id"],
        },
    },
]

DISPATCH = {
    "get_risk": get_risk,
    "get_restoration_estimate": get_restoration_estimate,
    "get_prep_guidance": get_prep_guidance,
    "get_alert_info": get_alert_info,
}
