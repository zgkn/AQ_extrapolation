"""Shared constants and math for the Singapore haze (PM2.5 / PSI) dashboard.

CAVEAT: Singapore's official PSI is max() over six pollutant sub-indices
(PM2.5, PM10, SO2, CO, O3, NO2). Everything in this project only models the
PM2.5 sub-index via the breakpoint table below. On days where another
pollutant dominates, the real PSI can be higher than what this pipeline
reports/projects.
"""
from __future__ import annotations

import datetime as dt

REGIONS = ["national", "north", "south", "east", "west", "central"]

API_BASE = "https://api-open.data.gov.sg/v2/real-time/api"
PM25_URL = f"{API_BASE}/pm25"
PSI_URL = f"{API_BASE}/psi"

HISTORY_PATH = "data/history.csv"
RETENTION_HOURS = 48
GAP_THRESHOLD_HOURS = 2  # if last row is older than this vs. now, treat as a missed run

CSV_FIELDS = [
    "timestamp",
    "region",
    "pm25_one_hourly",
    "psi_twenty_four_hourly",
    "pm25_twenty_four_hourly",
    "pm25_24h_source",  # "api" or "calculated"
]

# 24-hr avg PM2.5 (ug/m3) <-> PSI breakpoints, per NEA's published table
# (simplified/rounded per the task spec). Linear interpolation within each band.
PM25_PSI_BREAKPOINTS = [
    (0.0, 0),
    (12.0, 50),
    (55.4, 100),
    (150.4, 200),
    (250.4, 300),
    (350.4, 400),
    (500.4, 500),
]


def _interp(x, x0, x1, y0, y1):
    if x1 == x0:
        return y0
    return y0 + (x - x0) * (y1 - y0) / (x1 - x0)


def pm25_to_psi(pm25: float) -> float:
    """Convert 24-hr avg PM2.5 (ug/m3) to PSI via linear interpolation.

    Values below 0 clamp to 0; values above the table's top band (500.4)
    extrapolate linearly along the last segment's slope, since real haze
    events can exceed this simplified table's range.
    """
    if pm25 <= 0:
        return 0.0
    pts = PM25_PSI_BREAKPOINTS
    if pm25 >= pts[-1][0]:
        (x0, y0), (x1, y1) = pts[-2], pts[-1]
        return _interp(pm25, x0, x1, y0, y1)
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= pm25 <= x1:
            return _interp(pm25, x0, x1, y0, y1)
    return float(pts[-1][1])


def psi_to_pm25(psi: float) -> float:
    """Inverse of pm25_to_psi: PSI -> 24-hr avg PM2.5 (ug/m3)."""
    if psi <= 0:
        return 0.0
    pts = PM25_PSI_BREAKPOINTS
    if psi >= pts[-1][1]:
        (x0, y0), (x1, y1) = pts[-2], pts[-1]
        return _interp(psi, y0, y1, x0, x1)
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if y0 <= psi <= y1:
            return _interp(psi, y0, y1, x0, x1)
    return float(pts[-1][0])


def projected_avg_pm25(baseline: float, latest: float, t_hours: float) -> float:
    """Projected 24-hr avg PM2.5 at t hours ahead, assuming the latest 1-hr
    reading holds flat and linearly displaces the 24-hr window.

    NOTE: this is a simplification, not a forecast -- real PM2.5 will not
    actually hold perfectly flat.
    """
    t = max(0.0, min(24.0, t_hours))
    return ((24 - t) * baseline + t * latest) / 24


def time_to_threshold(baseline: float, latest: float, target_psi: float):
    """Hours until the projected 24-hr avg PSI reaches target_psi, holding
    the latest 1-hr PM2.5 reading flat.

    Returns a dict:
      - {"reachable": True, "hours": t} if 0 <= t <= 24
      - {"reachable": False, "needed_flat_pm25": X} otherwise, where
        needed_flat_pm25 is the sustained 1-hr PM2.5 that *would* need to
        hold flat for the full 24h window to bring the 24-hr average PSI to
        target_psi by hour 24 (at t=24 the whole window is replaced by the
        flat value, so the needed value is simply the target's PM2.5
        equivalent -- included for clarity even though it follows directly
        from the model).
    """
    target_pm25 = psi_to_pm25(target_psi)
    if latest == baseline:
        if abs(baseline - target_pm25) < 1e-9:
            return {"reachable": True, "hours": 0.0}
        return {"reachable": False, "needed_flat_pm25": target_pm25}

    t = 24 * (target_pm25 - baseline) / (latest - baseline)
    if 0 <= t <= 24:
        return {"reachable": True, "hours": t}
    return {"reachable": False, "needed_flat_pm25": target_pm25}


def parse_ts(ts: str) -> dt.datetime:
    """Parse an ISO-8601 timestamp (as returned by data.gov.sg) into an
    aware datetime."""
    s = ts.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    d = dt.datetime.fromisoformat(s)
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return d
