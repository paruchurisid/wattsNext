"""Bounded, restartable HTTP range reads for publisher CSV files.

EAGLE-I's five-column export has one physical line per observation. Overlapping
range boundaries retain each complete CSV record exactly once.
"""

from concurrent.futures import ThreadPoolExecutor
import io
import os
from pathlib import Path
import pandas as pd
from tenacity import retry, stop_after_attempt, wait_exponential
from .common import get, LOG


def csv_window(payload, offset, stop, total):
    request_start = max(0, offset - 1)
    left = 0 if offset == 0 else payload.index(b"\n") + 1
    if stop >= total:
        right = len(payload)
    else:
        index = payload.find(b"\n", stop - request_start - 1)
        if index < 0:
            raise ValueError("CSV record exceeds range overlap")
        right = index + 1
    return payload[left:right]


def timestamp_window(info, start, end):
    """Conservative byte bounds for the publisher's time-ordered CSV export."""
    total = info["size"]
    probes = {}

    def probe(offset):
        stop = min(total - 1, offset + 65535)
        with get(
            info["download_url"],
            headers={"Range": f"bytes={offset}-{stop}"},
            stream=True,
        ) as response:
            if response.status_code != 206:
                raise ValueError("Byte ranges unavailable")
            payload = b"".join(response.iter_content(65536))
        lines = payload.splitlines()
        # Skip a partial first record, or the header at byte zero.
        if len(lines) < 2:
            raise ValueError("Cannot locate a complete outage record")
        value = pd.Timestamp(lines[1].decode().rsplit(",", 1)[-1].strip())
        probes[offset] = value
        ordered = sorted(probes.items())
        if any(x[1] > y[1] for x, y in zip(ordered, ordered[1:])):
            raise ValueError("Outage export is not chronologically ordered")
        return value

    def bound(target):
        low = 0
        high = total - 65536
        while high - low > 65536:
            mid = (low + high) // 2
            if probe(mid) < target:
                low = mid
            else:
                high = mid
        return max(0, low - 65536), min(total, high + 131072)

    left = (
        0
        if pd.Timestamp(start) == pd.Timestamp(pd.Timestamp(start).year, 1, 1)
        else bound(pd.Timestamp(start))[0]
    )
    right = bound(pd.Timestamp(end) + pd.Timedelta(days=1))[1]
    return left, right


def filtered_csv_ranges(
    info, year, cache, normalize, workers=None, block_size=16 * 1024 * 1024, window=None
):
    workers = workers or max(
        1, min(32, int(os.environ.get("EAGLE_RANGE_WORKERS", "8")))
    )
    total = info["size"]
    suffix = "" if block_size == 16 * 1024 * 1024 else f"-{block_size}"
    directory = Path(cache) / (f"parts-{year}-{info['id']}-{total}" + suffix)
    directory.mkdir(parents=True, exist_ok=True)
    # A one-line header request is bounded and confirms byte-range support.
    with get(
        info["download_url"], headers={"Range": "bytes=0-4095"}, stream=True
    ) as response:
        if response.status_code != 206:
            raise ValueError("Publisher no longer supports byte-range downloads")
        header = response.raw.read(4096).split(b"\n", 1)[0] + b"\n"
    lower, upper = timestamp_window(info, *window) if window else (0, total)
    offsets = list(range((lower // block_size) * block_size, upper, block_size))

    @retry(
        stop=stop_after_attempt(4), wait=wait_exponential(min=1, max=30), reraise=True
    )
    def fetch(offset):
        path = directory / f"{offset:012d}.parquet"
        if path.exists():
            return pd.read_parquet(path)
        stop = min(offset + block_size, total)
        begin = max(0, offset - 1)
        with get(
            info["download_url"],
            headers={"Range": f"bytes={begin}-{min(stop + 65536, total) - 1}"},
            stream=True,
        ) as response:
            if response.status_code != 206:
                raise ValueError("Server ignored CSV byte range")
            expected_range = f"bytes {begin}-{min(stop + 65536, total) - 1}/{total}"
            if response.headers.get("Content-Range") != expected_range:
                raise ValueError("Publisher returned the wrong CSV byte range")
            payload = b"".join(response.iter_content(1024 * 1024))
        expected = min(stop + 65536, total) - begin
        if len(payload) != expected:
            raise IOError("Truncated CSV range")
        body = csv_window(payload, offset, stop, total)
        if offset:
            body = header + body
        frame = pd.read_csv(io.BytesIO(body), dtype=str)
        frame = normalize(frame, f"{year}-01-01", f"{year}-12-31")
        temp = path.with_suffix(".tmp")
        frame.to_parquet(temp, index=False)
        temp.replace(path)
        LOG.info(
            "EAGLE-I %s: range %.0f/%.0f MB filtered (%s target rows)",
            year,
            stop / 1e6,
            total / 1e6,
            len(frame),
        )
        return frame

    with ThreadPoolExecutor(max_workers=workers) as pool:
        frames = list(pool.map(fetch, offsets))
    return pd.concat(frames, ignore_index=True)
