---
name: sg-haze-dashboard
description: Rebuild, extend, or debug the Singapore PM2.5/PSI haze-tracking GitHub Actions pipeline in this repo (scripts/fetch_data.py, scripts/build_dashboard.py, .github/workflows/haze-dashboard.yml, data/history.csv). Use when asked about this project's haze dashboard, PSI projections, data.gov.sg air quality data, or when setting up a similar incremental-fetch-and-commit pipeline elsewhere.
---

# Singapore Haze Dashboard pipeline

## What this is

An hourly GitHub Actions pipeline that tracks Singapore PM2.5 + PSI from
data.gov.sg and projects when PSI will cross 100/150/200, using
git-commit-as-persistence (no external DB/cache/artifacts).

## Files

- `scripts/aq_lib.py` -- shared constants, the PM2.5<->PSI breakpoint table,
  and projection math (`pm25_to_psi`, `psi_to_pm25`, `projected_avg_pm25`,
  `time_to_threshold`).
- `scripts/fetch_data.py` -- incremental fetcher. Each run does a cheap
  "latest only" call (no `date` param) to both endpoints, and additionally
  backfills via `?date=YYYY-MM-DD` per missing day if the last row in
  `data/history.csv` is more than ~2h stale (missed run or first run).
  Dedupes on `(timestamp, region)`, retains 48h of history (dashboard only
  needs 24h; the buffer protects against a missed run needing backfill).
- `scripts/build_dashboard.py` -- renders `dashboard.png`: past-24h PSI
  (solid) + PM2.5 (secondary axis) + projected PSI (dashed) with threshold
  lines/ETAs for 100/150/200.
- `.github/workflows/haze-dashboard.yml` -- hourly cron + `workflow_dispatch`,
  runs fetch -> build -> `git pull --rebase` -> commit + push
  `data/history.csv` and `dashboard.png`.

## Data sources (no API key needed)

- `GET https://api-open.data.gov.sg/v2/real-time/api/pm25` --
  `data.items[].readings.pm25_one_hourly.{region}`, region in
  national/north/south/east/west/central.
- `GET https://api-open.data.gov.sg/v2/real-time/api/psi` --
  `data.items[].readings.psi_twenty_four_hourly.{region}` (official 24-hr PSI).
- Both support `?date=YYYY-MM-DD` (psi) or `YYYY-MM-DDTHH:mm:ss` (pm25) for
  backfill, and `paginationToken` in `data` if the response is paginated.
- **Gotcha:** some fetchers/caches silently drop `?date=`. Always check the
  response's own echoed date/timestamp against what was requested --
  `fetch_data.check_date_echo()` logs a warning if they don't match.
- Whether `/psi` also returns a direct 24-hr avg PM2.5 field (e.g.
  `pm25_twenty_four_hourly`) was **unconfirmed** when this pipeline was
  built (network access to data.gov.sg was blocked in that build
  environment). `fetch_data.find_pm25_24h_key()` checks for this field
  defensively at runtime and prefers it if present; otherwise it falls back
  to back-calculating from `psi_twenty_four_hourly` via the breakpoint
  table. Check `data/history.csv`'s `pm25_24h_source` column (`api` vs
  `calculated`) to see which path is actually active, and update this note
  once confirmed.

## PSI<->PM2.5 breakpoint table

24-hr avg PM2.5 (ug/m3) <-> PSI, linear interpolation within each band:
`0<->0, 12.0<->50, 55.4<->100, 150.4<->200, 250.4<->300, 350.4<->400, 500.4<->500`.

## Projection model

Given current 24-hr baseline `B` and latest 1-hr reading `X` held flat:

- `avg(t) = [(24-t)*B + t*X] / 24` for `0<=t<=24` hours ahead.
- Time to reach a target PSI: `t = 24*(target_pm25 - B)/(X - B)`, valid only
  if `0<=t<=24`. Otherwise report the sustained flat `X` that *would* reach
  the target by t=24 (at t=24 the window is fully replaced by `X`, so that
  value is just `target_pm25` itself).

## Known simplifications (keep these caveats in any code/comments touching this)

- Real PSI is `max()` over six pollutant sub-indices (PM2.5, PM10, SO2, CO,
  O3, NO2); this pipeline only models the PM2.5 sub-index.
- The flat-PM2.5 projection is a simplification for a quick "if nothing
  changes" read, not a real forecast.

## Common follow-up tasks

- **Add a region/dashboard**: `build_dashboard.py` currently hardcodes
  `REGION = "national"`; `data/history.csv` already stores all six regions,
  so add a loop or a CLI arg rather than refetching.
- **Change thresholds**: edit `THRESHOLDS` in `build_dashboard.py`.
- **Debug a bad run**: check the Action's logs for `run type: latest only`
  vs `latest + backfill(...)`, and the `retention: trimmed N row(s)` line.
- **If pushes start conflicting**: the workflow already does
  `git pull --rebase` before pushing with a small retry loop; if failures
  persist, check for overlapping schedule + manual `workflow_dispatch` runs
  and consider tightening the `concurrency` group (already set to serialize
  runs of this workflow).
