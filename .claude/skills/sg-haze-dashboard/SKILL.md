---
name: sg-haze-dashboard
description: Rebuild, extend, or debug the Singapore PM2.5/PSI haze-tracking GitHub Actions pipeline in this repo (scripts/fetch_data.py, scripts/build_dashboard.py, scripts/build_map.py, .github/workflows/haze-dashboard.yml, data/history.csv, docs/index.html). Use when asked about this project's haze dashboard, the GitHub Pages map site, PSI projections, data.gov.sg air quality data, or when setting up a similar incremental-fetch-and-commit pipeline elsewhere.
---

# Singapore Haze Dashboard pipeline

## What this is

An hourly GitHub Actions pipeline that tracks Singapore PM2.5 + PSI from
data.gov.sg and projects when PSI will cross 100/150/200, using
git-commit-as-persistence (no external DB/cache/artifacts). Publishes both a
PNG chart and a small GitHub Pages website (a Folium map).

## Files

- `scripts/aq_lib.py` -- shared constants, the PM2.5<->PSI breakpoint table,
  projection math (`pm25_to_psi`, `psi_to_pm25`, `projected_avg_pm25`,
  `time_to_threshold`), and `compute_payload(rows, region)` -- the one place
  that turns a region's CSV rows into {history, projection, thresholds}, used
  by both `build_dashboard.py` and `build_map.py` so their numbers can't drift.
- `scripts/fetch_data.py` -- incremental fetcher. Each run does a cheap
  "latest only" call (no `date` param) to both endpoints, and additionally
  backfills via `?date=YYYY-MM-DD` per missing day if the last row in
  `data/history.csv` is more than ~2h stale (missed run or first run).
  Dedupes on `(timestamp, region)`, retains 48h of history (dashboard only
  needs 24h; the buffer protects against a missed run needing backfill).
- `scripts/build_dashboard.py` -- renders `dashboard.png`: two stacked
  single-axis panels (PSI, then PM2.5 -- deliberately *not* one dual-axis
  plot, which invents a correlation between two differently-scaled series)
  with projected PSI (dashed) and threshold lines/ETAs for 100/150/200.
- `scripts/build_map.py` -- renders `docs/index.html`: a Folium/Leaflet map
  of Singapore with a colored marker per region (NEA PSI band colors), a
  popup per marker with current PSI/PM2.5 and threshold ETAs, and a header
  banner with the national figures. Uses plain `OpenStreetMap` tiles
  (`tiles="OpenStreetMap"`) deliberately -- CartoDB's basemaps now require an
  API key, which would break on a public site with no key configured.
  `REGION_COORDS` are approximate representative points for each region, not
  official boundaries.
- `.github/workflows/haze-dashboard.yml` -- hourly cron + `workflow_dispatch`,
  runs fetch -> build_dashboard -> build_map -> `git pull --rebase` -> commit
  + push `data/history.csv`, `dashboard.png`, and `docs/index.html`.

## GitHub Pages

`docs/index.html` is only reachable at a URL once Pages is turned on for the
repo (Settings -> Pages -> Source: Deploy from a branch -> the default branch,
folder `/docs`). This is a one-time manual step -- no tool in this session can
flip that setting; if asked to "make the site live", tell the user to do this
(or check whether it's already on) rather than assuming the workflow alone
publishes it.

## Data sources (no API key needed)

- `GET https://api-open.data.gov.sg/v2/real-time/api/pm25` --
  `data.items[].readings.pm25_one_hourly.{region}`.
- `GET https://api-open.data.gov.sg/v2/real-time/api/psi` --
  `data.items[].readings.psi_twenty_four_hourly.{region}` (official 24-hr PSI).
- **Confirmed against the live API: there is no "national" region key** in
  either endpoint, despite that being assumed at spec time -- only
  `aq_lib.API_REGIONS` (north/south/east/west/central). `aq_lib.REGIONS` adds
  `"national"` on top as a nationwide aggregate that `fetch_data.py`
  synthesizes itself (`synthesize_national()`): the mean of whichever of the
  five regions have a value, per timestamp. Its `pm25_24h_source` reads
  `derived_national_mean` in the CSV so it's never confused for a real API
  field.
- Both support `?date=YYYY-MM-DD` (psi) or `YYYY-MM-DDTHH:mm:ss` (pm25) for
  backfill, and `paginationToken` in `data` if the response is paginated.
- **Gotcha:** some fetchers/caches silently drop `?date=`. Always check the
  response's own echoed date/timestamp against what was requested --
  `fetch_data.check_date_echo()` logs a warning if they don't match.
- **Confirmed against the live API** (first real workflow run): `/psi` does
  return a direct 24-hr avg PM2.5 field, `pm25_twenty_four_hourly`, so
  `fetch_data.py` reads it straight rather than back-calculating (the
  back-calculation path still exists in `find_pm25_24h_key()` as a fallback
  if that field is ever renamed/removed). Check `data/history.csv`'s
  `pm25_24h_source` column (`api` vs `calculated`) to confirm which path is
  active for any given row.
- **Rate limiting:** the live API 429'd on a burst backfill (6 requests in
  ~2s during the very first run's 3-day backfill). `fetch_data.get_with_retry()`
  retries 429/5xx with backoff (honoring `Retry-After`), and the backfill
  loop paces consecutive day-requests `BACKFILL_REQUEST_DELAY_S` apart. If
  backfills start failing again, raise that delay or the retry count first.

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

- **Add a region to the PNG**: `build_dashboard.py` currently hardcodes
  `REGION = "national"`; `data/history.csv` already stores all six regions
  (the map already plots five of them), so add a loop or a CLI arg rather
  than refetching.
- **Change thresholds**: edit `THRESHOLDS` in `aq_lib.py` (shared by both
  `build_dashboard.py` and `build_map.py`/`compute_payload`).
- **Change PSI band colors/cutoffs on the map**: edit `PSI_BANDS` in
  `build_map.py`.
- **Debug a bad run**: check the Action's logs for `run type: latest only`
  vs `latest + backfill(...)`, and the `retention: trimmed N row(s)` line.
- **If pushes start conflicting**: the workflow already does
  `git pull --rebase` before pushing with a small retry loop; if failures
  persist, check for overlapping schedule + manual `workflow_dispatch` runs
  and consider tightening the `concurrency` group (already set to serialize
  runs of this workflow).
