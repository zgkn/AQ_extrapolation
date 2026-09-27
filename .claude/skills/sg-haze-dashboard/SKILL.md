---
name: sg-haze-dashboard
description: Rebuild, extend, or debug the Singapore PM2.5/PSI haze-tracking GitHub Actions pipeline in this repo (scripts/fetch_data.py, scripts/build_dashboard.py, .github/workflows/haze-dashboard.yml, data/history.csv, docs/index.html, docs/data.json). Use when asked about this project's haze dashboard, the GitHub Pages site, PSI projections, data.gov.sg air quality data, or when setting up a similar incremental-fetch-and-commit pipeline elsewhere.
---

# Singapore Haze Dashboard pipeline

## What this is

An hourly GitHub Actions pipeline that tracks Singapore PM2.5 + PSI from
data.gov.sg and projects when PSI will cross 100/150/200, using
git-commit-as-persistence (no external DB/cache/artifacts). Publishes a
GitHub Pages site with an interactive (drag-to-pan, scroll/pinch-to-zoom)
time-series chart -- PM2.5 and PSI for each of the five real regions, with
a dashed PSI projection toward the thresholds.

## Files

- `scripts/aq_lib.py` -- shared constants, the PM2.5<->PSI breakpoint table,
  projection math (`pm25_to_psi`, `psi_to_pm25`, `projected_avg_pm25`,
  `time_to_threshold`), and `compute_payload(rows, region)` -- the one place
  that turns a region's CSV rows into {history, projection, thresholds}.
- `scripts/fetch_data.py` -- incremental fetcher. Each run does a cheap
  "latest only" call (no `date` param) to both endpoints, and additionally
  backfills via `?date=YYYY-MM-DD` per missing day if the last row in
  `data/history.csv` is more than ~2h stale (missed run or first run).
  Dedupes on `(timestamp, region)`, retains `aq_lib.RETENTION_HOURS` (72h)
  of history -- the dashboard only shows `aq_lib.HISTORY_WINDOW_HOURS` (48h)
  of it; the extra buffer protects against a missed run needing backfill.
- `scripts/build_dashboard.py` -- writes `docs/data.json` (the numbers,
  via `compute_payload` per region) and `docs/index.html` (a static page,
  identical bytes every run -- it reads `data.json` client-side, so only
  the data file actually changes each commit). No matplotlib/PNG anymore;
  the chart is a hand-rolled SVG rendered and made interactive entirely in
  `index.html`'s inline `<script>` -- Python only computes, the browser
  only renders + pans/zooms already-computed numbers. Two stacked
  single-axis panels -- PM2.5, then PSI -- deliberately *not* one dual-axis
  plot, which invents a correlation between two differently-scaled series.
  Each of the five real regions (`aq_lib.API_REGIONS`) gets a fixed
  categorical color (`REGION_COLORS` in `build_dashboard.py` -- the only
  copy; it's written into `data.json`'s `colors` key and the JS always
  reads it from there, never hardcodes it) shared between both panels. The PSI
  panel adds a dashed flat-PM2.5 projection per region and threshold lines
  at 100/150/200; a dashed line crossing a threshold line **is** that
  region's ETA -- no per-region ETA text (5 regions x 3 thresholds would
  clutter the chart), but hovering shows exact values via the crosshair
  tooltip, and the full numbers are in `data.json`/the table-view toggle.
  Interaction: drag pans, wheel/pinch zooms (centered on the cursor,
  clamped to the actual data range and a 3h minimum span), both panels
  share one time domain so they pan/zoom in lockstep, "Reset view" restores
  the full range. Also writes `docs/.nojekyll` (see below).
- `.github/workflows/haze-dashboard.yml` -- hourly cron + `workflow_dispatch`,
  runs fetch -> build_dashboard -> `git pull --rebase` -> commit + push
  `data/history.csv`, `docs/data.json`, `docs/index.html`, `docs/.nojekyll`.

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

- **Add/remove a plotted region**: edit `build_dashboard.py`'s
  `REGION_COLORS` dict (and iterate `API_REGIONS` accordingly) --
  `data/history.csv` also stores a synthesized `national` row per timestamp
  (see below) if a nationwide line/figure is ever wanted again.
- **Change thresholds**: edit `THRESHOLDS` in `aq_lib.py` -- both the
  chart's threshold lines and `compute_payload`'s ETA math import it from
  there, so there's one place to change.
- **Change how much history the chart shows**: edit
  `HISTORY_WINDOW_HOURS` in `aq_lib.py` (currently 48h). If you push it
  past `RETENTION_HOURS` (72h), raise that too, or the chart will just
  show whatever's left after trimming.
- **Change region colors**: edit `REGION_COLORS` in `build_dashboard.py`.
  Keep a fixed order and don't cycle/reuse hues across regions --
  see the dataviz skill if adding a 6th+ series.
- **Tune pan/zoom feel**: in `index.html`'s script, `MIN_SPAN_MS` (3h) is
  the closest zoom-in, `STEP_CANDIDATES_MS` + `MIN_PX_PER_TICK` (78px)
  control x-axis tick density (recomputed from the *actual measured*
  container width on every render/resize -- don't hardcode a tick count,
  it was the cause of an actual bug: labels overlapping into mush on a
  narrow phone screen until tick count was made width-aware), and the
  wheel handler's `1.15` factor is the zoom speed per scroll tick.
- **Touch/mobile pan+pinch**: `attachInteraction()` in `index.html` tracks
  every active pointer per panel (`pointers` map keyed by `pointerId`) --
  1 pointer = pan (drag), 2 = pinch-zoom anchored at their midpoint,
  releasing one finger of a pinch continues as a fresh pan from the
  remaining finger. Real touch gestures don't fire `wheel` events, so
  zoom must go through this path on mobile -- if pan/zoom feels broken on
  a phone, check this logic, not the wheel handler. Note
  `svg.setPointerCapture(...)` is wrapped in try/catch: it can throw in
  edge cases (confirmed while testing with synthetic Playwright pointer
  events, which aren't browser-"active" pointers), and since it's called
  synchronously inside the pointerdown listener, an uncaught throw there
  would abort the rest of that handler -- silently skipping the
  drag/pinch-state setup that follows it. Test this interaction with
  Playwright by dispatching real two-pointer `PointerEvent`s
  (`pointerType: 'touch'`) directly, since Playwright's `touchscreen` API
  has no multi-touch/pinch primitive.
- **Any datetime formatting/display added later (in the JS)**: use
  `Intl.DateTimeFormat` with `timeZone: "Asia/Singapore"` (see `fmtSGT()`
  in `index.html`), never a bare `Date` method -- `toLocaleString()`/etc
  without an explicit timeZone use the *viewer's* browser timezone, not
  Singapore's. This bit us once already in the matplotlib-PNG version
  (its `DateFormatter` silently rendered ticks in UTC, 8h behind the
  title); the JS rewrite's tick-alignment math (`timeTicks()`) also needs
  the explicit `SG_OFFSET_MS` shift, or ticks land on odd times relative
  to SGT hour boundaries.
- **Debug a bad run**: check the Action's logs for `run type: latest only`
  vs `latest + backfill(...)`, and the `retention: trimmed N row(s)` line.
- **If pushes start conflicting**: the workflow already does
  `git pull --rebase` before pushing with a small retry loop; if failures
  persist, check for overlapping schedule + manual `workflow_dispatch` runs
  and consider tightening the `concurrency` group (already set to serialize
  runs of this workflow).
