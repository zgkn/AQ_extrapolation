"""Backfills Singapore PM2.5/PSI history from a fixed start date (default:
August 1 of the current year) through now, into data/episodes_history.csv.

This is deliberately independent of data/history.csv -- the live dashboard's
rolling RETENTION_HOURS (60-day) window doesn't reach back far enough for a
"since August" haze-episode search, and this script has no retention of its
own: it keeps everything from the start date forward.

Reuses fetch_data.py's request/retry/parsing machinery (same API, same
resilience to connection errors and persistent per-day failures -- a day
that fails after retries are exhausted is skipped, not fatal to the run),
but writes to its own file via its own save()/load_existing(), since
fetch_data.py's are hardcoded to HISTORY_PATH.

No API key is required for these data.gov.sg v2 real-time endpoints.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import logging
import os
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(__file__))
from aq_lib import CSV_FIELDS, PM25_URL, PSI_URL, parse_ts  # noqa: E402
from fetch_data import (  # noqa: E402
    BACKFILL_REQUEST_DELAY_S,
    check_date_echo,
    fetch_items,
    rows_from_items,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("fetch_episodes_data")

EPISODES_HISTORY_PATH = "data/episodes_history.csv"


def default_start_date(today: dt.date) -> dt.date:
    """August 1 of the current year, or of last year if that's still in the
    future (e.g. running this in, say, March)."""
    start = dt.date(today.year, 8, 1)
    return start if start <= today else dt.date(today.year - 1, 8, 1)


def day_range(start: dt.date, end: dt.date) -> list[str]:
    days = []
    d = start
    while d <= end:
        days.append(d.isoformat())
        d += dt.timedelta(days=1)
    return days


def load_existing() -> dict[tuple[str, str], dict]:
    rows: dict[tuple[str, str], dict] = {}
    if not os.path.exists(EPISODES_HISTORY_PATH):
        return rows
    with open(EPISODES_HISTORY_PATH, newline="") as f:
        for r in csv.DictReader(f):
            rows[(r["timestamp"], r["region"])] = r
    return rows


def save(rows: dict[tuple[str, str], dict]) -> None:
    os.makedirs(os.path.dirname(EPISODES_HISTORY_PATH), exist_ok=True)
    ordered = sorted(rows.values(), key=lambda r: (r["timestamp"], r["region"]))
    with open(EPISODES_HISTORY_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in ordered:
            writer.writerow({k: row.get(k, "") for k in CSV_FIELDS})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--start-date",
        default=None,
        help="YYYY-MM-DD; default is August 1 of the current year (or last year if that's in the future)",
    )
    args = parser.parse_args()

    now = dt.datetime.now(dt.timezone.utc)
    today = now.date()
    start = dt.date.fromisoformat(args.start_date) if args.start_date else default_start_date(today)
    if start > today:
        raise SystemExit(f"--start-date {start} is in the future (today is {today})")

    days = day_range(start, today)
    log.info("backfilling %d day(s): %s .. %s", len(days), days[0], days[-1])

    existing = load_existing()
    new_rows: dict[tuple[str, str], dict] = {}
    failed_days = []
    for i, day in enumerate(days):
        if i > 0:
            time.sleep(BACKFILL_REQUEST_DELAY_S)
        try:
            pm25_items, echo1 = fetch_items(PM25_URL, date=day)
            check_date_echo(day, echo1, PM25_URL)
            time.sleep(BACKFILL_REQUEST_DELAY_S)
            psi_items, echo2 = fetch_items(PSI_URL, date=day)
            check_date_echo(day, echo2, PSI_URL)
        except requests.exceptions.RequestException as e:
            # A day that still fails after fetch_items' own retries are
            # exhausted shouldn't abort the whole backfill and discard every
            # other day already fetched -- skip it and keep going (same
            # lesson learned the hard way in fetch_data.py's deep backfill).
            log.warning("giving up on day=%s after retries exhausted (%s) -- skipping", day, e)
            failed_days.append(day)
            continue
        day_rows = rows_from_items(pm25_items, psi_items)
        new_rows.update(day_rows)
        if (i + 1) % 10 == 0 or (i + 1) == len(days):
            log.info("...%d/%d day(s) fetched", i + 1, len(days))

    if failed_days:
        log.warning("%d/%d day(s) failed and were skipped: %s", len(failed_days), len(days), ", ".join(failed_days))

    merged = dict(existing)
    merged.update(new_rows)
    added = len(merged) - len(existing)
    log.info("fetched %d row(s), %d new after dedup on (timestamp, region)", len(new_rows), added)

    save(merged)
    log.info("wrote %d row(s) to %s", len(merged), EPISODES_HISTORY_PATH)


if __name__ == "__main__":
    main()
