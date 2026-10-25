from concierge import engine
from .monte_carlo import simulate

def topology(case, repairs_complete=False):
    return [{"stage":"substation_breaker","order":1,"status":"complete" if repairs_complete else "restored_first"},
            {"stage":"sectionalizer_fuse","order":2,"status":"complete" if repairs_complete else "queued"},
            {"stage":"service_transformer","order":3,"status":"complete" if repairs_complete else "queued"}]
def estimate(case, access_blocked=False, extra_crews=0, repairs_complete=False):
    raw = engine.restoration_effort(case, access_blocked, extra_crews, repairs_complete)
    # The scheduler has already applied crew parallelism to the base duration.
    # Do not compress a single repair again just because more crews are present.
    mc = simulate(raw["reference_effort_hours"], crew_count=1,
                  access_penalty=3 if access_blocked and not repairs_complete else 0)
    return {**raw, "monte_carlo": mc, "topology": topology(case, repairs_complete),
            "multiplier": 4.5, "drive_time_added": False}
