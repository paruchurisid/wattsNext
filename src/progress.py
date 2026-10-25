"""Offline progress for restartable, county-filtered outage archive downloads."""

from pathlib import Path
import json


def progress(cache):
    root = Path(cache) / "eagle"
    catalog = root / "catalog.json"
    if not catalog.exists():
        return {
            "status": "not_started",
            "completed_bytes": 0,
            "total_bytes": 0,
            "years": [],
        }
    metadata = json.loads(catalog.read_text(encoding="utf-8"))
    years = []
    for info in metadata["files"]:
        year = info["year"]
        size = info["size"]
        identity = f"{year}-{info['id']}-{size}"
        annual = root / (identity + ".parquet")
        directory = root / ("parts-" + identity)
        if annual.exists():
            completed = size
        else:
            completed = (
                sum(
                    min(16 * 1024 * 1024, size - int(p.stem))
                    for p in directory.glob("*.parquet")
                )
                if directory.exists()
                else 0
            )
        years.append(
            {
                "year": year,
                "complete": annual.exists(),
                "completed_bytes": completed,
                "total_bytes": size,
            }
        )
    total = sum(v["total_bytes"] for v in years)
    complete = sum(v["completed_bytes"] for v in years)
    return {
        "status": "complete" if all(y["complete"] for y in years) else "in_progress",
        "completed_bytes": complete,
        "total_bytes": total,
        "completed_percent": round(100 * complete / total, 2) if total else 0,
        "years": years,
        "note": "Counts durable complete range checkpoints; bytes in active transfers are excluded.",
    }
