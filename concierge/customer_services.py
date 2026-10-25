"""Preparation guidance and alert generation. Tailored only to what the
customer declares — never to anything inferred about them."""

ESTIMATE_CHANGE_THRESHOLD_HOURS = 2.0

ALERT_TYPES = ["pre_storm", "outage_confirmed", "estimate_updated", "restoration_complete"]
ALERT_TIMINGS = {
    "pre_storm": "Example shown before a storm.",
    "outage_confirmed": "Example shown when damage could affect this home.",
    "estimate_updated": "Example shown if the repair time changes by 2 hours or more.",
    "restoration_complete": "Example shown when repairs are marked complete.",
}


def prep_guidance(household, risk):
    needs = household["declared_needs"]
    actions = [
        "Charge phones and essential devices now, before any outage starts.",
        "Keep flashlights and batteries nearby. Use flashlights instead of candles.",
        "Stay away from fallen or sagging power lines. Report them to your power company.",
    ]

    if risk["band"] in ("Moderate", "High"):
        actions.append("Keep a few days of drinking water, food that does not need a fridge, and your medicines ready.")

    if needs.get("power_bank"):
        actions.append("Save your power bank for your phone and other essential devices. Medical equipment needs provider-approved backup power.")

    if needs.get("needs_phone_for_work"):
        actions.append("Tell your employer you may lose phone service. Plan another way to charge your phone or get in touch.")

    if needs.get("medical_device"):
        actions.append(
            "SAFETY: contact your medical device provider now for a backup-power plan. "
            "A power bank or generic battery is not a substitute for provider-approved backup power."
        )

    return actions


def alert_eligibility(household):
    return {
        "eligible": household["alert_opt_in"],
        "channel": household["alert_channel"] if household["alert_opt_in"] else None,
        "reason": "Example notifications are turned on for this household." if household["alert_opt_in"] else "Example notifications are turned off for this household.",
    }


def escalation_triggers(household):
    triggers = [
        {"trigger": "The repair time changes by 2 hours or more", "action": "Show an updated example message."},
        {"trigger": "Repairs are marked complete", "action": "Show a message that repairs are done in this example."},
    ]
    if household["declared_needs"].get("medical_device"):
        triggers.append({
            "trigger": "You use medical equipment that needs electricity",
            "action": "Call your device provider to make a backup-power plan. This does not guarantee faster power repairs.",
        })
    return triggers


def _channel_label(channel):
    return {"sms": "SMS", "email": "Email"}.get(channel, channel or "none")


def build_alert_previews(household, case, estimate, previous_estimate=None):
    channel = household["alert_channel"]
    city = household["city"]
    previews = []

    previews.append({
        "type": "pre_storm",
        "timing": ALERT_TIMINGS["pre_storm"],
        "channel": _channel_label(channel),
        "message": f"Example for {city}: A storm warning would remind you to charge devices and check your supplies.",
    })

    if case["damage_items"] and any(not d.get("repaired", True) for d in case["damage_items"]):
        previews.append({
            "type": "outage_confirmed",
            "timing": ALERT_TIMINGS["outage_confirmed"],
            "channel": _channel_label(channel),
            "message": f"Example for {city}: Damaged equipment could affect this home's power. Repairs could take {estimate['low_hours']:.1f}-{estimate['high_hours']:.1f} hours. Your power company has not confirmed these times.",
        })

    moved = previous_estimate is not None and abs(estimate["high_hours"] - previous_estimate["high_hours"]) >= ESTIMATE_CHANGE_THRESHOLD_HOURS
    if moved:
        previews.append({
            "type": "estimate_updated",
            "timing": ALERT_TIMINGS["estimate_updated"],
            "channel": _channel_label(channel),
            "message": f"Example update: Repairs could now take {estimate['low_hours']:.1f}-{estimate['high_hours']:.1f} hours (previously {previous_estimate['low_hours']:.1f}-{previous_estimate['high_hours']:.1f} hours). Your power company has not confirmed these times.",
        })

    if estimate["reference_effort_hours"] == 0.0:
        previews.append({
            "type": "restoration_complete",
            "timing": ALERT_TIMINGS["restoration_complete"],
            "channel": _channel_label(channel),
            "message": f"Example for {city}: Repairs are marked done. If your power is still off, check your breakers, then report it to your power company.",
        })

    return previews
