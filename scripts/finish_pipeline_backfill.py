"""Finish the current backfill as soon as its durable downloads are complete.

This is a one-shot execution helper, not a recurring/scheduled monitor. It keeps
the final normalization and validation attached to a long transfer even if the
interactive shell is interrupted.
"""

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout-minutes", type=int, default=360)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    cache = root / "data/cache/eagle"
    plan = json.loads((cache / "catalog.json").read_text(encoding="utf-8"))
    expected = [
        cache / f"{f['year']}-{f['id']}-{f['size']}.parquet" for f in plan["files"]
    ]
    deadline = time.monotonic() + args.timeout_minutes * 60
    previous = -1
    while True:
        complete = sum(p.exists() for p in expected)
        if complete != previous:
            print(
                f"County-filtered annual downloads ready: {complete}/{len(expected)}",
                flush=True,
            )
            previous = complete
        if complete == len(expected):
            break
        if time.monotonic() > deadline:
            raise TimeoutError(
                "Annual archive transfer incomplete; rerun preload_outages.py and this helper to resume"
            )
        time.sleep(5)
    print(
        "All downloads ready. Building and validating the four final products.",
        flush=True,
    )
    command = [
        sys.executable,
        str(root / "run_all.py"),
        "--skip-smoke",
        "--start-year",
        "2015",
        "--end-year",
        "2026",
    ]
    return subprocess.run(command, cwd=root).returncode


if __name__ == "__main__":
    raise SystemExit(main())
