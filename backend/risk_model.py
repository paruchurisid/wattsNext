def backtest():
    return {"brier_skill_score": 0.0, "roc_auc": 0.5, "is_calibrated": False,
            "reliability_curve": [], "status": "fallback: insufficient validated historical signal"}
def risk_payload(case, repairs_complete=False):
    if repairs_complete: band = "Low"
    elif any(not x.get("repaired", True) for x in case.get("damage_items", [])): band = "High"
    else: band = {"calm":"Low", "moderate":"Moderate", "severe":"High"}[case["storm_setting"]]
    return {"band": band, "is_calibrated": False, "backtest": backtest()}
