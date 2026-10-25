import random

def simulate(base_hours, iterations=2500, seed=42, crew_count=1, access_penalty=0.0):
    rng = random.Random(seed)
    # deterministic log-normal approximation; crews compress independent work
    scale = max(0.55, 1 / max(crew_count, 1) ** 0.35)
    samples = [base_hours * scale * rng.lognormvariate(0, 0.18) + access_penalty for _ in range(iterations)]
    samples.sort()
    q = lambda p: round(samples[min(len(samples)-1, int((len(samples)-1)*p))], 1)
    return {"iterations": iterations, "p10": q(.10), "p50": q(.50), "p90": q(.90)}
