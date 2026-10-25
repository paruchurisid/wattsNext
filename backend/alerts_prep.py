STAGES = ["PRE_STORM_ADVISORY", "OUTAGE_CONFIRMED", "ETR_UPDATED", "POWER_RESTORED"]
def lifecycle(repairs_complete=False, estimate_changed=False):
    return [{"stage": s, "triggered": (s=="POWER_RESTORED" and repairs_complete) or (s=="ETR_UPDATED" and estimate_changed)} for s in STAGES]
