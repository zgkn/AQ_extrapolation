"""Builds docs/haze2015/data.json from data/haze2015_history.csv -- raw
PM2.5/PSI history for Singapore's June-November 2015 haze crisis.

No projection, no thresholds: unlike the live dashboard, this is purely
historical, so there's nothing to forecast -- just the two actual-value
panels (PM2.5 1-hr, PSI 24-hr) for the whole fixed window, consumed by the
"2015 Haze" tab of the main docs/index.html dashboard (see
build_dashboard.py), fetched lazily the first time that tab is opened.

Run scripts/fetch_haze2015_data.py first to populate
data/haze2015_history.csv -- this script only reads it, it never hits the
network itself.
"""
from __future__ import annotations

import csv
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from aq_lib import API_REGIONS, to_float  # noqa: E402
from build_dashboard import REGION_COLORS  # noqa: E402
from fetch_haze2015_data import HAZE2015_END, HAZE2015_HISTORY_PATH, HAZE2015_START  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("build_haze2015_page")

DOCS_DIR = "docs/haze2015"
DATA_PATH = os.path.join(DOCS_DIR, "data.json")


def load_all_rows() -> dict[str, list[dict]]:
    by_region: dict[str, list[dict]] = {r: [] for r in API_REGIONS}
    if not os.path.exists(HAZE2015_HISTORY_PATH):
        raise SystemExit(f"{HAZE2015_HISTORY_PATH} does not exist -- run scripts/fetch_haze2015_data.py first")
    with open(HAZE2015_HISTORY_PATH, newline="") as f:
        for row in csv.DictReader(f):
            if row["region"] in by_region:
                by_region[row["region"]].append(row)
    for rows in by_region.values():
        rows.sort(key=lambda r: r["timestamp"])
    return by_region


def main() -> None:
    by_region = load_all_rows()
    regions = {}
    for region, rows in by_region.items():
        history = [
            {
                "t": r["timestamp"],
                "pm25_1h": to_float(r["pm25_one_hourly"]),
                "psi": to_float(r["psi_twenty_four_hourly"]),
            }
            for r in rows
        ]
        if history:
            regions[region] = {"history": history}
        else:
            log.warning("no data for region=%s -- omitting from chart", region)

    if not regions:
        raise SystemExit("no region had any data -- refusing to build an empty chart")

    os.makedirs(DOCS_DIR, exist_ok=True)
    out = {
        "colors": REGION_COLORS,
        "window_start": HAZE2015_START.isoformat(),
        "window_end": HAZE2015_END.isoformat(),
        "regions": regions,
    }
    with open(DATA_PATH, "w") as f:
        json.dump(out, f, indent=2)
    log.info("wrote %s (%d region(s))", DATA_PATH, len(regions))


if __name__ == "__main__":
    main()
