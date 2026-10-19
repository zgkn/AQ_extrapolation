"""One-time(ish) fetch of Singapore's 2015 Southeast Asian haze crisis
(June-November 2015) PM2.5/PSI history, into data/haze2015_history.csv.

Unlike fetch_data.py/fetch_episodes_data.py (which query the v2 real-time
API's per-day endpoints -- that API's rolling history doesn't reach back to
2015), 2015 data only exists in NEA's combined historical CSV datasets on
data.gov.sg, covering April 2014 through today:
  - "Historical 1-hr PM2.5" (regional: North/South/East/West/Central)
  - "Historical 24-hr PSI" (regional: North/South/East/West/Central)

These are downloaded via data.gov.sg's newer poll-download mechanism: GET
.../poll-download returns a signed URL to the *entire* dataset's CSV (no
server-side date-range query) -- so this script downloads the whole file
and filters to HAZE2015_START..HAZE2015_END locally.

The exact CSV column names aren't documented anywhere this script's author
could find -- extract_readings() matches region columns case-insensitively
and logs the raw header on every run, so a schema mismatch fails loudly and
visibly in the workflow log rather than silently writing an empty file.

No API key required for this public dataset.
"""
from __future__ import annotations

import csv
import datetime as dt
import logging
import os
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(__file__))
from aq_lib import API_REGIONS  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("fetch_haze2015_data")

HAZE2015_HISTORY_PATH = "data/haze2015_history.csv"
HAZE2015_FIELDS = ["timestamp", "region", "pm25_one_hourly", "psi_twenty_four_hourly"]

POLL_DOWNLOAD_BASE = "https://api-open.data.gov.sg/v1/public/api/datasets"
# "Historical 1-hr PM2.5" / "Historical 24-hr PSI" -- both regional, both
# covering Apr 2014 onward. Found via data.gov.sg's own dataset listings;
# re-verify at https://data.gov.sg/datasets/<id>/view if either 404s.
PM25_DATASET_ID = "d_6c0d5fc34838b12472475fdb73c0af29"
PSI_DATASET_ID = "d_b4cf557f8750260d229c49fd768e11ed"

HAZE2015_START = dt.date(2015, 6, 1)
HAZE2015_END = dt.date(2015, 11, 30)

POLL_INTERVAL_S = 3
POLL_MAX_ATTEMPTS = 10
REQUEST_TIMEOUT_S = 90


def get_download_url(dataset_id: str) -> str:
    """Poll .../poll-download until it returns a ready signed URL (code ==
    0). These are small, long-stable CSVs so the first call is typically
    already ready, but the API is documented as a poll loop -- retry a few
    times (well under its 5-req/min rate limit) just in case."""
    url = f"{POLL_DOWNLOAD_BASE}/{dataset_id}/poll-download"
    last_payload = None
    for attempt in range(1, POLL_MAX_ATTEMPTS + 1):
        resp = requests.get(url, timeout=REQUEST_TIMEOUT_S)
        resp.raise_for_status()
        payload = resp.json()
        last_payload = payload
        if payload.get("code") == 0 and payload.get("data", {}).get("url"):
            return payload["data"]["url"]
        log.info("poll-download not ready for %s (attempt %d/%d): %s", dataset_id, attempt, POLL_MAX_ATTEMPTS, payload)
        if attempt < POLL_MAX_ATTEMPTS:
            time.sleep(POLL_INTERVAL_S)
    raise RuntimeError(f"poll-download for dataset {dataset_id} never became ready; last response: {last_payload}")


def download_csv(url: str) -> list[dict]:
    resp = requests.get(url, timeout=REQUEST_TIMEOUT_S)
    resp.raise_for_status()
    text = resp.content.decode("utf-8-sig")
    lines = text.splitlines()
    log.info("raw first 2 line(s): %r", lines[:2])
    rows = list(csv.DictReader(lines))
    log.info("downloaded %d total row(s) from %s", len(rows), url.split("?")[0])
    if rows:
        log.info("sample row(s): %r", rows[:2])
    return rows


SGT = dt.timezone(dt.timedelta(hours=8))

# Confirmed against a real poll-download response: this dataset's first
# column is headered with the metric name (e.g. "1hr_pm25"/"24hr_psi")
# rather than literally "timestamp", and its values are D/M/YYYY H:MM --
# no leading zeros, bare SGT, not ISO 8601 (e.g. "1/4/2014 1:00"). The
# ISO fallback is defensive in case NEA ever changes the export format.
_TS_FORMATS = ("%d/%m/%Y %H:%M",)


def parse_ts(ts_str: str) -> dt.datetime:
    for fmt in _TS_FORMATS:
        try:
            return dt.datetime.strptime(ts_str, fmt).replace(tzinfo=SGT)
        except ValueError:
            continue
    ts = dt.datetime.fromisoformat(ts_str)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=SGT)
    return ts


def in_window(ts: dt.datetime) -> bool:
    return HAZE2015_START <= ts.date() <= HAZE2015_END


def extract_readings(csv_rows: list[dict], label: str) -> dict[tuple[str, str], float]:
    """Wide-format rows (one column per region) -> {(timestamp_iso, region): value}."""
    if not csv_rows:
        log.warning("%s: CSV had zero rows", label)
        return {}
    header = list(csv_rows[0].keys())
    log.info("%s: CSV header: %s", label, header)

    ts_field = None
    for cand in ("timestamp", "date", "datetime"):
        if cand in header:
            ts_field = cand
            break
    if ts_field is None:
        ts_field = header[0]
        log.warning("%s: no obvious timestamp column in %s -- guessing first column %r", label, header, ts_field)

    region_fields: dict[str, str] = {}
    for region in API_REGIONS:
        for col in header:
            if col.strip().lower() == region:
                region_fields[region] = col
                break
    missing = [r for r in API_REGIONS if r not in region_fields]
    if missing:
        raise RuntimeError(f"{label}: CSV header {header} is missing expected region column(s): {missing}")

    out: dict[tuple[str, str], float] = {}
    unparseable_ts = 0
    for row in csv_rows:
        ts_raw = row.get(ts_field)
        if not ts_raw:
            continue
        try:
            ts = parse_ts(ts_raw)
        except ValueError:
            unparseable_ts += 1
            continue
        if not in_window(ts):
            continue
        for region, col in region_fields.items():
            raw = row.get(col)
            if raw in (None, "", "NA", "N.A.", "-"):
                continue
            try:
                out[(ts.isoformat(), region)] = float(raw)
            except ValueError:
                continue
    if unparseable_ts:
        log.warning("%s: skipped %d row(s) with unparseable timestamps (sample field value: %r)", label, unparseable_ts, ts_field)
    return out


def main() -> None:
    log.info("fetching PM2.5 dataset %s", PM25_DATASET_ID)
    pm25_url = get_download_url(PM25_DATASET_ID)
    pm25_readings = extract_readings(download_csv(pm25_url), "PM2.5")
    log.info("parsed %d PM2.5 reading(s) in window %s..%s", len(pm25_readings), HAZE2015_START, HAZE2015_END)

    log.info("fetching PSI dataset %s", PSI_DATASET_ID)
    psi_url = get_download_url(PSI_DATASET_ID)
    psi_readings = extract_readings(download_csv(psi_url), "PSI")
    log.info("parsed %d PSI reading(s) in window %s..%s", len(psi_readings), HAZE2015_START, HAZE2015_END)

    all_keys = sorted(set(pm25_readings) | set(psi_readings))
    if not all_keys:
        raise SystemExit("no PM2.5 or PSI readings found in the 2015 window -- check dataset IDs/schema above")

    os.makedirs(os.path.dirname(HAZE2015_HISTORY_PATH), exist_ok=True)
    with open(HAZE2015_HISTORY_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HAZE2015_FIELDS)
        writer.writeheader()
        for ts_iso, region in all_keys:
            writer.writerow({
                "timestamp": ts_iso,
                "region": region,
                "pm25_one_hourly": pm25_readings.get((ts_iso, region), ""),
                "psi_twenty_four_hourly": psi_readings.get((ts_iso, region), ""),
            })
    log.info("wrote %d row(s) to %s", len(all_keys), HAZE2015_HISTORY_PATH)


if __name__ == "__main__":
    main()
