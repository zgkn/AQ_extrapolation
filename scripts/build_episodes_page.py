"""Finds haze episodes (contiguous stretches where a region's 24-hr PSI was
above PSI_EPISODE_THRESHOLD) in data/episodes_history.csv and builds
docs/episodes/data.json -- consumed by the "Past episodes" tab of the main
docs/index.html dashboard (see build_dashboard.py), which fetches this file
lazily the first time that tab is opened. This script only writes the data;
the page itself lives in build_dashboard.py's INDEX_HTML.

Run scripts/fetch_episodes_data.py first to populate
data/episodes_history.csv -- this script only reads it, it never hits the
network itself.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from aq_lib import API_REGIONS, parse_ts, to_float  # noqa: E402
from build_dashboard import REGION_COLORS  # noqa: E402
from fetch_episodes_data import EPISODES_HISTORY_PATH  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("build_episodes_page")

DOCS_DIR = "docs/episodes"
DATA_PATH = os.path.join(DOCS_DIR, "data.json")

PSI_EPISODE_THRESHOLD = 100
BUFFER_HOURS = 24


def load_all_rows(path: str) -> dict[str, list[dict]]:
    by_region: dict[str, list[dict]] = {r: [] for r in API_REGIONS}
    if not os.path.exists(path):
        raise SystemExit(f"{path} does not exist -- run scripts/fetch_episodes_data.py first")
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            if row["region"] in by_region:
                by_region[row["region"]].append(row)
    for rows in by_region.values():
        rows.sort(key=lambda r: r["timestamp"])
    return by_region


def find_episodes(rows: list[dict]) -> list[dict]:
    """Contiguous runs of psi_twenty_four_hourly > PSI_EPISODE_THRESHOLD, in
    chronological order. A gap (missing/None reading, or a reading back at
    or below the threshold) ends the current run."""
    episodes: list[dict] = []
    current: dict | None = None
    for r in rows:
        psi = to_float(r["psi_twenty_four_hourly"])
        if psi is not None and psi > PSI_EPISODE_THRESHOLD:
            ts = parse_ts(r["timestamp"])
            if current is None:
                current = {"start": ts, "end": ts, "peak_psi": psi, "peak_time": ts}
            else:
                current["end"] = ts
                if psi > current["peak_psi"]:
                    current["peak_psi"] = psi
                    current["peak_time"] = ts
        elif current is not None:
            episodes.append(current)
            current = None
    if current is not None:
        episodes.append(current)
    return episodes


def build_episode_payload(region: str, episode: dict, rows: list[dict]) -> dict:
    window_start = episode["start"] - dt.timedelta(hours=BUFFER_HOURS)
    window_end = episode["end"] + dt.timedelta(hours=BUFFER_HOURS)
    series = []
    for r in rows:
        ts = parse_ts(r["timestamp"])
        if window_start <= ts <= window_end:
            series.append({
                "t": r["timestamp"],
                "pm25_1h": to_float(r["pm25_one_hourly"]),
                "psi": to_float(r["psi_twenty_four_hourly"]),
            })
    return {
        "region": region,
        "episode_start": episode["start"].isoformat(),
        "episode_end": episode["end"].isoformat(),
        "peak_psi": round(episode["peak_psi"], 1),
        "peak_time": episode["peak_time"].isoformat(),
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "series": series,
    }


def main() -> None:
    by_region = load_all_rows(EPISODES_HISTORY_PATH)

    all_ts = [parse_ts(r["timestamp"]) for rows in by_region.values() for r in rows]
    if not all_ts:
        raise SystemExit(f"{EPISODES_HISTORY_PATH} has no rows -- nothing to search")

    episodes = []
    for region in API_REGIONS:
        rows = by_region[region]
        found = find_episodes(rows)
        log.info("region=%s: %d episode(s) found above PSI %d", region, len(found), PSI_EPISODE_THRESHOLD)
        for episode in found:
            episodes.append(build_episode_payload(region, episode, rows))

    episodes.sort(key=lambda e: e["episode_start"], reverse=True)
    for i, ep in enumerate(episodes):
        ep["id"] = f"{ep['region']}-{i}"

    os.makedirs(DOCS_DIR, exist_ok=True)
    out = {
        "colors": REGION_COLORS,
        "threshold": PSI_EPISODE_THRESHOLD,
        "buffer_hours": BUFFER_HOURS,
        "search_start": min(all_ts).isoformat(),
        "search_end": max(all_ts).isoformat(),
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "episodes": episodes,
    }
    with open(DATA_PATH, "w") as f:
        json.dump(out, f, indent=2)
    log.info("wrote %s (%d episode(s) total)", DATA_PATH, len(episodes))


if __name__ == "__main__":
    main()
