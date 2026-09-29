"""Incremental fetcher for Singapore PM2.5 + PSI readings from data.gov.sg.

Each run:
  1. Fetches the *latest* reading only (no `date` param) from both endpoints
     -- cheap, and all that's needed when runs aren't missed.
  2. If the last timestamp already in data/history.csv is more than
     ~GAP_THRESHOLD_HOURS old (missed run, or this is the very first run),
     also backfills via `?date=YYYY-MM-DD` for each missing day.
  3. Merges everything into data/history.csv, deduped on (timestamp, region),
     then trims rows older than RETENTION_HOURS relative to the newest row.

No API key is required for these data.gov.sg v2 real-time endpoints.
"""
from __future__ import annotations

import csv
import datetime as dt
import logging
import os
import re
import sys
import time
from typing import Iterable

import requests

sys.path.insert(0, os.path.dirname(__file__))
from aq_lib import (  # noqa: E402
    API_REGIONS,
    CSV_FIELDS,
    GAP_THRESHOLD_HOURS,
    HISTORY_PATH,
    PM25_URL,
    PSI_URL,
    RETENTION_HOURS,
    parse_ts,
    psi_to_pm25,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("fetch_data")

REQUEST_TIMEOUT = 30
MAX_RETRIES = 4
BACKFILL_REQUEST_DELAY_S = 1.5  # pace consecutive backfill calls so we don't trip the API's rate limit

# 24-hr avg PM2.5 is exposed directly on /psi as `pm25_twenty_four_hourly`
# (confirmed against the live API); this pattern is a defensive fallback in
# case data.gov.sg ever renames/removes it -- see find_pm25_24h_key below.
PM25_24H_KEY_PATTERN = re.compile(r"pm.?2.?5", re.IGNORECASE)


def get_with_retry(url: str, params: dict) -> requests.Response:
    """GET with retry/backoff on 429 and 5xx -- data.gov.sg rate-limits
    bursts of requests (seen in practice during a multi-day backfill), and
    honors a Retry-After header on 429."""
    for attempt in range(1, MAX_RETRIES + 1):
        resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        if resp.status_code == 429 or resp.status_code >= 500:
            if attempt == MAX_RETRIES:
                resp.raise_for_status()
            retry_after = resp.headers.get("Retry-After")
            wait = float(retry_after) if retry_after else min(2 ** attempt, 30)
            log.warning("HTTP %d from %s (attempt %d/%d) -- retrying in %.1fs", resp.status_code, url, attempt, MAX_RETRIES, wait)
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return resp
    raise RuntimeError("unreachable")  # loop always returns or raises above


def fetch_items(url: str, date: str | None = None) -> tuple[list[dict], str | None]:
    """Fetch all items from a data.gov.sg v2 real-time endpoint, following
    `paginationToken` if present. Returns (items, echoed_date_or_None)."""
    items: list[dict] = []
    params: dict = {}
    if date:
        params["date"] = date
    token = None
    echoed_date = None
    while True:
        if token:
            params["paginationToken"] = token
        resp = get_with_retry(url, params)
        payload = resp.json()
        data = payload.get("data", {})
        page_items = data.get("items", [])
        items.extend(page_items)
        if page_items and echoed_date is None:
            echoed_date = page_items[0].get("date") or page_items[0].get("timestamp")
        token = data.get("paginationToken")
        if not token:
            break
    return items, echoed_date


def check_date_echo(requested_date: str, echoed: str | None, url: str) -> None:
    """Gotcha guard: some fetchers/caches silently drop `?date=`. Verify the
    response's own date/timestamp actually matches what was requested."""
    if echoed is None:
        log.warning("no items returned for date=%s from %s; cannot verify echo", requested_date, url)
        return
    if not echoed.startswith(requested_date):
        log.warning(
            "date param may have been dropped: requested date=%s but response echoes %r from %s",
            requested_date,
            echoed,
            url,
        )


def find_pm25_24h_key(readings: dict) -> str | None:
    """Look for a 24-hr avg PM2.5 field on a /psi reading item. Prefers the
    exact name suggested in the task, but falls back to any key that looks
    like a PM2.5 field and isn't the 1-hr one, so this adapts if data.gov.sg
    names it slightly differently."""
    if "pm25_twenty_four_hourly" in readings:
        return "pm25_twenty_four_hourly"
    for key in readings:
        if key == "pm25_one_hourly":
            continue
        if PM25_24H_KEY_PATTERN.search(key) and "one_hourly" not in key:
            return key
    return None


def rows_from_items(pm25_items: Iterable[dict], psi_items: Iterable[dict]) -> dict[tuple[str, str], dict]:
    """Merge parsed pm25 + psi items into {(timestamp, region): row_dict}."""
    rows: dict[tuple[str, str], dict] = {}

    pm25_24h_key_seen = None
    logged_pm25_region_keys = False

    for item in pm25_items:
        ts = item.get("timestamp")
        if not ts:
            continue
        readings = item.get("readings", {}).get("pm25_one_hourly", {})
        if not logged_pm25_region_keys:
            logged_pm25_region_keys = True
            unknown = set(readings) - set(API_REGIONS)
            missing = set(API_REGIONS) - set(readings)
            if unknown or missing:
                log.warning("pm25_one_hourly region keys seen=%s vs expected API_REGIONS=%s (unknown=%s, missing=%s)",
                            sorted(readings), API_REGIONS, sorted(unknown), sorted(missing))
        for region in API_REGIONS:
            if region not in readings:
                continue
            key = (ts, region)
            row = rows.setdefault(key, {"timestamp": ts, "region": region})
            row["pm25_one_hourly"] = readings[region]

    logged_psi_region_keys = False
    for item in psi_items:
        ts = item.get("timestamp")
        if not ts:
            continue
        all_readings = item.get("readings", {})
        psi_readings = all_readings.get("psi_twenty_four_hourly", {})
        pm25_24h_key = find_pm25_24h_key(all_readings)
        if pm25_24h_key and pm25_24h_key_seen is None:
            pm25_24h_key_seen = pm25_24h_key
            log.info("psi response includes a 24-hr PM2.5 field: %r -- using it directly", pm25_24h_key)
        pm25_24h_readings = all_readings.get(pm25_24h_key, {}) if pm25_24h_key else {}
        if not logged_psi_region_keys:
            logged_psi_region_keys = True
            unknown = set(psi_readings) - set(API_REGIONS)
            missing = set(API_REGIONS) - set(psi_readings)
            if unknown or missing:
                log.warning("psi_twenty_four_hourly region keys seen=%s vs expected API_REGIONS=%s (unknown=%s, missing=%s)",
                            sorted(psi_readings), API_REGIONS, sorted(unknown), sorted(missing))

        for region in API_REGIONS:
            if region not in psi_readings:
                continue
            key = (ts, region)
            row = rows.setdefault(key, {"timestamp": ts, "region": region})
            psi_val = psi_readings[region]
            row["psi_twenty_four_hourly"] = psi_val
            if region in pm25_24h_readings:
                row["pm25_twenty_four_hourly"] = pm25_24h_readings[region]
                row["pm25_24h_source"] = "api"
            else:
                row["pm25_twenty_four_hourly"] = round(psi_to_pm25(psi_val), 2)
                row["pm25_24h_source"] = "calculated"

    if pm25_24h_key_seen is None and psi_items:
        log.info("psi response has no 24-hr PM2.5 field -- back-calculating from psi_twenty_four_hourly")

    synthesize_national(rows)
    return rows


def synthesize_national(rows: dict[tuple[str, str], dict]) -> None:
    """The live API has no "national" region key -- only the five in
    API_REGIONS. Add a nationwide row per timestamp as the mean of whichever
    of those five have data, so downstream consumers (the PNG's default
    region, the map's header banner) still get a headline figure. Mutates
    `rows` in place, adding a ("timestamp", "national") entry per timestamp
    that has at least one real region's reading."""
    by_ts: dict[str, list[dict]] = {}
    for (ts, region), row in rows.items():
        if region != "national":
            by_ts.setdefault(ts, []).append(row)

    def mean(field: str, region_rows: list[dict]):
        vals = [r[field] for r in region_rows if r.get(field) is not None]
        return round(sum(vals) / len(vals), 2) if vals else None

    for ts, region_rows in by_ts.items():
        pm25_1h = mean("pm25_one_hourly", region_rows)
        psi = mean("psi_twenty_four_hourly", region_rows)
        pm25_24h = mean("pm25_twenty_four_hourly", region_rows)
        if pm25_1h is None and psi is None and pm25_24h is None:
            continue
        rows[(ts, "national")] = {
            "timestamp": ts,
            "region": "national",
            "pm25_one_hourly": pm25_1h,
            "psi_twenty_four_hourly": psi,
            "pm25_twenty_four_hourly": pm25_24h,
            "pm25_24h_source": "derived_national_mean",
        }


def load_existing() -> dict[tuple[str, str], dict]:
    rows: dict[tuple[str, str], dict] = {}
    if not os.path.exists(HISTORY_PATH):
        return rows
    with open(HISTORY_PATH, newline="") as f:
        for r in csv.DictReader(f):
            rows[(r["timestamp"], r["region"])] = r
    return rows


def latest_timestamp(rows: dict[tuple[str, str], dict]) -> dt.datetime | None:
    if not rows:
        return None
    return max(parse_ts(r["timestamp"]) for r in rows.values())


def save(rows: dict[tuple[str, str], dict]) -> None:
    os.makedirs(os.path.dirname(HISTORY_PATH), exist_ok=True)
    ordered = sorted(rows.values(), key=lambda r: (r["timestamp"], r["region"]))
    with open(HISTORY_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in ordered:
            writer.writerow({k: row.get(k, "") for k in CSV_FIELDS})


def trim_retention(rows: dict[tuple[str, str], dict]) -> dict[tuple[str, str], dict]:
    if not rows:
        return rows
    newest = max(parse_ts(r["timestamp"]) for r in rows.values())
    cutoff = newest - dt.timedelta(hours=RETENTION_HOURS)
    kept = {k: r for k, r in rows.items() if parse_ts(r["timestamp"]) >= cutoff}
    trimmed = len(rows) - len(kept)
    log.info("retention: trimmed %d row(s) older than %dh before %s", trimmed, RETENTION_HOURS, newest.isoformat())
    return kept


def find_gap_days(rows: dict[tuple[str, str], dict]) -> list[str]:
    """Scan existing history per region for internal gaps -- a missed run
    can "heal" on the next run's cheap 'latest only' fetch (the trailing
    timestamp looks recent again) without that next run ever going back to
    refetch the specific hour(s) it missed, leaving a permanent hole in the
    middle of the history. Returns the day(s) (YYYY-MM-DD) spanning any gap
    wider than GAP_THRESHOLD_HOURS, per region, so main() can re-backfill
    them alongside (or even without) a trailing-edge gap."""
    days: set[str] = set()
    for region in API_REGIONS:
        timestamps = sorted(parse_ts(r["timestamp"]) for (_, rgn), r in rows.items() if rgn == region)
        for prev, cur in zip(timestamps, timestamps[1:]):
            if (cur - prev) > dt.timedelta(hours=GAP_THRESHOLD_HOURS):
                d = prev.date()
                while d <= cur.date():
                    days.add(d.isoformat())
                    d += dt.timedelta(days=1)
    return sorted(days)


def find_leading_gap_days(rows: dict[tuple[str, str], dict], now: dt.datetime) -> list[str]:
    """If the *earliest* retained row is more recent than RETENTION_HOURS
    would allow -- typically because RETENTION_HOURS/HISTORY_WINDOW_HOURS
    was just raised in aq_lib.py -- backfill the days between the retention
    boundary and that earliest row, so a config change takes effect on the
    very next run instead of the dashboard slowly growing into the new
    window over the following weeks/months. Distinct from find_gap_days(),
    which only looks *between* existing rows, never before the earliest
    one."""
    if not rows:
        return []
    earliest = min(parse_ts(r["timestamp"]) for r in rows.values())
    boundary = now - dt.timedelta(hours=RETENTION_HOURS)
    if earliest <= boundary + dt.timedelta(hours=GAP_THRESHOLD_HOURS):
        return []
    days = []
    d = boundary.date()
    while d <= earliest.date():
        days.append(d.isoformat())
        d += dt.timedelta(days=1)
    return days


def missing_days(last_ts: dt.datetime | None, now: dt.datetime) -> list[str]:
    if last_ts is None:
        # first-ever run: seed with a small lookback so the dashboard has
        # something to plot immediately.
        start = (now - dt.timedelta(hours=RETENTION_HOURS)).date()
    else:
        start = last_ts.date()
    days = []
    d = start
    while d <= now.date():
        days.append(d.isoformat())
        d += dt.timedelta(days=1)
    return days


def main() -> None:
    now = dt.datetime.now(dt.timezone.utc)
    existing = load_existing()
    last_ts = latest_timestamp(existing)

    # Step 1: always do the cheap "latest only" fetch.
    pm25_items, _ = fetch_items(PM25_URL)
    psi_items, _ = fetch_items(PSI_URL)
    new_rows = rows_from_items(pm25_items, psi_items)

    run_kind = "latest only"

    trailing_gap = last_ts is None or (now - last_ts) > dt.timedelta(hours=GAP_THRESHOLD_HOURS)
    internal_gap_days = find_gap_days(existing)
    leading_gap_days = find_leading_gap_days(existing, now)
    if trailing_gap or internal_gap_days or leading_gap_days:
        days = sorted(set(missing_days(last_ts, now)) | set(internal_gap_days) | set(leading_gap_days))
        run_kind = f"latest + backfill({len(days)} day(s): {', '.join(days)})"
        if last_ts is None:
            log.info("no existing history found -- treating as first-ever run, backfilling %d day(s)", len(days))
        elif trailing_gap:
            log.info(
                "gap detected: last recorded timestamp %s is more than %dh old -- backfilling %d day(s)",
                last_ts.isoformat(),
                GAP_THRESHOLD_HOURS,
                len(days),
            )
        if internal_gap_days:
            log.info(
                "internal gap(s) found in existing history (a missed run that later self-healed) -- "
                "re-backfilling day(s): %s",
                ", ".join(internal_gap_days),
            )
        if leading_gap_days:
            log.info(
                "retained history doesn't reach back as far as RETENTION_HOURS allows (likely just raised) -- "
                "backfilling leading day(s): %s",
                ", ".join(leading_gap_days),
            )
        for i, day in enumerate(days):
            if i > 0:
                time.sleep(BACKFILL_REQUEST_DELAY_S)
            day_pm25_items, echo1 = fetch_items(PM25_URL, date=day)
            check_date_echo(day, echo1, PM25_URL)
            time.sleep(BACKFILL_REQUEST_DELAY_S)
            day_psi_items, echo2 = fetch_items(PSI_URL, date=day)
            check_date_echo(day, echo2, PSI_URL)
            day_rows = rows_from_items(day_pm25_items, day_psi_items)
            new_rows.update(day_rows)
    else:
        log.info("last recorded timestamp %s is recent -- skipping backfill", last_ts.isoformat() if last_ts else "n/a")

    log.info("run type: %s", run_kind)

    merged = dict(existing)
    merged.update(new_rows)
    added = len(merged) - len(existing)
    log.info("fetched %d row(s), %d new after dedup on (timestamp, region)", len(new_rows), added)

    merged = trim_retention(merged)
    save(merged)
    log.info("wrote %d row(s) to %s", len(merged), HISTORY_PATH)


if __name__ == "__main__":
    main()
