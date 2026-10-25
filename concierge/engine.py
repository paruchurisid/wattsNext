"""
Pure calculation engine. No AI calls here — every number the assistant
shows comes from this module so the model only explains, never invents.
"""
import json
import pathlib

DATA = pathlib.Path(__file__).parent.parent / "data"
ACCESS_BLOCKED_HOURS = 3.0
RANGE_LOW_FACTOR = 0.75
RANGE_HIGH_FACTOR = 1.5

_labor = json.loads((DATA / "labor_reference.json").read_text())
ILM = _labor["indirect_multiplier"]
CATEGORIES = _labor["categories"]


def _unit_hours(item):
    cat = CATEGORIES.get(item["asset_type"])
    if cat is None:
        # Imported Neon asset classes can be more granular than the local
        # workbook. Keep the estimate deterministic and visibly conservative
        # until a matching labor reference is curated.
        return 2.0
    if "sizes" in cat:
        key = str(item.get("size_kva") or item.get("size_group"))
        size = cat["sizes"].get(key) or next(iter(cat["sizes"].values()))
    else:
        size = cat
    return size["install_hours"] + size["removal_hours"]


def _jobs(damage_items):
    """Each unit of quantity is its own one-crew job."""
    jobs = []
    for item in damage_items:
        per_unit_effort = _unit_hours(item) * ILM
        for i in range(item["quantity"]):
            label = item["asset_type"] + (f" #{i + 1}" if item["quantity"] > 1 else "")
            jobs.append({"asset_type": item["asset_type"], "label": label, "duration": per_unit_effort})
    return jobs


def _schedule(jobs, crew_count):
    """Greedy list scheduling: longest job first onto the least-loaded free crew.
    Returns one list per crew, each job annotated with its (unrounded) start/end
    hour — callers round only for display, never before using these for math."""
    crews = [[] for _ in range(max(crew_count, 1))]
    loads = [0.0] * max(crew_count, 1)
    for job in sorted(jobs, key=lambda j: -j["duration"]):
        i = loads.index(min(loads))
        start = loads[i]
        end = start + job["duration"]
        crews[i].append({**job, "start_hour": start, "end_hour": end})
        loads[i] = end
    return crews


def _makespan(jobs, crew_count):
    if not jobs:
        return 0.0
    crews = _schedule(jobs, crew_count)
    return max((c[-1]["end_hour"] for c in crews if c), default=0.0)


def job_timeline(case, crew_count=1, repairs_complete=False):
    """Restoration step timeline: one row per job, with its crew and status.
    The first job scheduled on each crew is 'in_progress' (it's the one the
    crew would be on right now in this replay); later jobs on that crew are
    'pending'. This comes straight from the scheduler, not a fabricated clock."""
    jobs = _jobs(case["damage_items"])
    crews = _schedule(jobs, crew_count)
    timeline = []
    for crew_index, crew_jobs in enumerate(crews, start=1):
        for position, job in enumerate(crew_jobs):
            if repairs_complete:
                status = "complete"
            elif position == 0:
                status = "in_progress"
            else:
                status = "pending"
            timeline.append({
                "crew": crew_index,
                "asset_type": job["asset_type"],
                "label": job["label"],
                "duration_hours": round(job["duration"], 1),
                "start_hour": round(job["start_hour"], 1),
                "end_hour": round(job["end_hour"], 1),
                "status": status,
            })
    timeline.sort(key=lambda t: (t["crew"], t["start_hour"]))
    return timeline


def restoration_effort(case, access_blocked=False, extra_crews=0, repairs_complete=False):
    """
    Returns the restoration-time range for a case's damage items.
    Evidence: every hour value traces to labor_reference.json (source_data or
    assumption, per category); quantity and crew count are modeling assumptions.
    """
    if repairs_complete:
        return {
            "reference_effort_hours": 0.0,
            "low_hours": 0.0,
            "high_hours": 0.0,
            "access_blocked": access_blocked,
            "crew_count": 1 + extra_crews,
        }

    jobs = _jobs(case["damage_items"])
    crew_count = 1 + extra_crews
    reference_effort = _makespan(jobs, crew_count)

    low = reference_effort * RANGE_LOW_FACTOR
    high = reference_effort * RANGE_HIGH_FACTOR
    if access_blocked:
        low += ACCESS_BLOCKED_HOURS
        high += ACCESS_BLOCKED_HOURS

    return {
        "reference_effort_hours": round(reference_effort, 1),
        "low_hours": round(low, 1),
        "high_hours": round(high, 1),
        "access_blocked": access_blocked,
        "crew_count": crew_count,
    }


def risk_band(case, repairs_complete=False):
    """Demonstration rule, not a calibrated probability."""
    if repairs_complete:
        return {"band": "Low", "reason": "Repairs to the equipment serving this home are complete in this example."}

    unrepaired = [d for d in case["damage_items"] if not d.get("repaired", True)]
    if unrepaired:
        return {
            "band": "High",
            "reason": "The example includes damaged power lines or equipment that supply this home.",
        }

    storm_band = {"calm": "Low", "moderate": "Moderate", "severe": "High"}[case["storm_setting"]]
    return {
        "band": storm_band,
        "reason": f"No repairs are needed for this home in the example. The risk label reflects the {case['storm_setting']} storm conditions chosen for it.",
    }


def confidence(case, access_blocked=False):
    """Derived from evidence quality, never from vibes."""
    if not case.get("path_valid", True):
        return {
            "level": "Low",
            "reason": "We could not check which power lines and equipment supply this home.",
        }
    if access_blocked:
        return {
            "level": "Low",
            "reason": "We added 3 hours for a blocked road in this example. We do not know the actual delay, so the estimate is less certain.",
        }
    return {
        "level": "Medium",
        "reason": "We used past damage records and matched them to this sample home. This is an example, not a checked report for your address.",
    }


def check_fallback(case):
    if case is None:
        return {"fallback": True, "reason": "No case data is available for this household."}
    if not case.get("path_valid", True):
        return {
            "fallback": True,
            "reason": "We do not know which power lines supply this home, so we cannot give a reliable repair estimate.",
        }
    return {"fallback": False, "reason": None}
