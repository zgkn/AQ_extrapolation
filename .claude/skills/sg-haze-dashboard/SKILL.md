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
  backfills via `?date=YYYY-MM-DD` per day that's either (a) missing at the
  *trailing edge* -- the last row in `data/history.csv` is more than ~2h
  stale (missed run or first run), (b) an *internal* gap: see
  `find_gap_days()` below, or (c) missing at the *leading edge* -- the
  earliest retained row doesn't reach back as far as `RETENTION_HOURS`
  allows: see `find_leading_gap_days()` below. Dedupes on
  `(timestamp, region)`, retains `aq_lib.RETENTION_HOURS` (61 days) of
  history -- the dashboard only shows `aq_lib.HISTORY_WINDOW_HOURS`
  (60 days) of it; the extra buffer protects against a missed run needing
  backfill. A window of weeks (not 24-48h) is deliberate now that the chart
  pans/zooms: a longer default window gives useful long-range trend context
  (real haze episodes often build over several days, and month-to-month
  comparison needs even more) without hurting legibility, since users can
  zoom into any sub-range rather than being stuck with everything visible
  and cramped by default.
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
  the full range. A tap/click on a point (as opposed to a drag/pinch) pins
  the readings tooltip there -- see "Tap/click to pin readings" below. Also
  writes `docs/.nojekyll` (see below).
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
  retries 429/5xx *and* connection-level errors (see below) with backoff
  (honoring `Retry-After` on 429), and the backfill loop paces consecutive
  day-requests `BACKFILL_REQUEST_DELAY_S` apart. If backfills start failing
  again, raise that delay or the retry count first.
- **A single backfill day failing must never lose every other day's data**:
  confirmed in production during the one-time 58-day deep backfill after
  raising `RETENTION_HOURS` -- a plain `requests.exceptions.ConnectionError`
  (a network-level reset, no HTTP response at all) on day ~15 of ~58 wasn't
  caught by `get_with_retry()` (which only handled HTTP 429/5xx status
  codes), crashing the whole script. Because `fetch_data.py` only calls
  `save()` once at the very end of `main()`, that crash discarded all ~15
  days already fetched that run, and because the workflow's "Fetch" step had
  no `continue-on-error`, it also skipped the commit step entirely. Fixed
  two ways: (1) `get_with_retry()` now retries
  `requests.exceptions.RequestException` (covers connection resets,
  timeouts, etc.), not just HTTP status codes; (2) the backfill loop in
  `main()` wraps each day's fetch in its own try/except -- a day that still
  fails after `get_with_retry()` exhausts its retries is logged and skipped
  (it stays missing, so `find_gap_days()`/`find_leading_gap_days()` pick it
  back up next run) rather than aborting the whole run and losing every
  other day already merged into `new_rows`. The workflow's "Fetch" step also
  now has `continue-on-error: true` (mirroring the build step) so an
  unexpected crash there still lets the commit step run on whatever was
  fetched before failing, and the final gate step checks both steps'
  outcomes. Test this kind of fix by mocking `requests.get` to fail
  selectively (only for backfill/date requests, not the initial "latest
  only" calls) and confirming `main()` completes and saves rather than
  raising -- not by hitting the real API, which this session's own network
  policy blocks anyway (see the leading-edge-gaps note below).
- **Internal gaps (a hole in the *middle* of the history, not just a stale
  trailing edge)**: the original gap check only looked at whether the very
  *last* row was stale relative to "now" -- a single missed hourly run
  self-heals on the next run's cheap "latest only" fetch (the trailing
  timestamp looks recent again) without that next run ever going back to
  refetch the specific hour(s) it missed, leaving a permanent hole that
  would otherwise never get backfilled. `fetch_data.find_gap_days()` fixes
  this by scanning each region's own sorted timestamps in the *existing*
  history for any consecutive gap wider than `GAP_THRESHOLD_HOURS`,
  independent of whether the trailing edge is stale, and returns the day(s)
  spanning it; `main()` unions those days with the usual trailing-edge
  `missing_days()` set before backfilling. Per-region (not just "does *some*
  region have data for this timestamp") on purpose, since a partial-region
  hole (one region missing while others are fine) wouldn't show up if you
  only checked for the *existence* of a timestamp across any region. A gap
  the upstream API itself never had data for will keep getting re-detected
  and re-backfilled every run until it ages out of `RETENTION_HOURS` --
  wasteful but bounded and harmless, not worth suppressing.
- **Leading-edge gaps (raising `RETENTION_HOURS`/`HISTORY_WINDOW_HOURS`
  after history already exists)**: neither the trailing-edge check nor
  `find_gap_days()` looks *before* the earliest retained row, so simply
  raising the retention window in `aq_lib.py` wouldn't by itself backfill
  the newly-wanted older days -- the dashboard would just grow into the
  bigger window naturally over the following days/weeks/months, which
  isn't what you want when you increase it deliberately (e.g. 7 days -> 60
  days). `fetch_data.find_leading_gap_days()` compares the earliest
  retained timestamp against `now - RETENTION_HOURS`; if there's a gap, it
  returns the day(s) between them so `main()` backfills them on the very
  next run. This can mean a *lot* of day-requests in one run the first time
  you raise the window a long way (e.g. 7 -> 61 days is ~54 extra days x 2
  endpoints, paced `BACKFILL_REQUEST_DELAY_S` apart -- a few minutes, not
  instant); it self-resolves after that one run succeeds and never
  re-triggers unless the window is raised again. This can't be exercised
  from a local dev session if your egress network policy blocks
  `api-open.data.gov.sg` (only the GitHub Actions runner may have access) --
  verify with mocked `existing` rows instead (see `find_leading_gap_days()`
  in `fetch_data.py`), and let the actual backfill happen inside the next
  triggered workflow run.

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
  `HISTORY_WINDOW_HOURS` in `aq_lib.py` (currently 60 days). If you push it
  past `RETENTION_HOURS` (61 days), raise that too, or the chart will just
  show whatever's left after trimming. Raising either doesn't need a manual
  backfill -- `find_leading_gap_days()` (see above) makes the next
  triggered/scheduled run backfill the newly-included older days on its
  own.
- **Change region colors**: edit `REGION_COLORS` in `build_dashboard.py`.
  Keep a fixed order and don't cycle/reuse hues across regions --
  see the dataviz skill if adding a 6th+ series.
- **Tune pan/zoom feel**: in `index.html`'s script, `MIN_SPAN_MS` (3h) is
  the closest zoom-in, `STEP_CANDIDATES_MS` + `MIN_PX_PER_TICK` (65px)
  control x-axis tick density (recomputed from the *actual measured*
  container width on every render/resize -- don't hardcode a tick count,
  it was the cause of an actual bug: labels overlapping into mush on a
  narrow phone screen until tick count was made width-aware; if you lower
  `MIN_PX_PER_TICK` further to pack in even more ticks, re-check mobile
  widths for overlap, don't just eyeball desktop), and the wheel handler's
  `1.15` factor is the zoom speed per scroll tick.
- **Scatter markers**: `drawMarkers()` draws a small dot at each real data
  point on top of the line, but only when `countInView()` (points inside
  the *current* pan/zoom window, not the whole dataset) is under
  `MAX_MARKER_POINTS` (60) -- 5 regions x a week of hourly data is ~170
  points/line fully zoomed out, and drawing dots for all of that would be
  a smear, not a scatter plot. This means markers only appear once the
  viewer zooms in far enough for them to be legible, which is intentional,
  not a bug -- if markers seem to be "missing," check whether the current
  view has too many visible points first.
- **Tap/click to pin readings**: plain hover already showed a tooltip on
  mouse, but that's useless on touch (no hover) and disappears the instant
  the pointer leaves. `attachInteraction()` now distinguishes a tap/click
  (pointerdown -> pointerup with < `TAP_MAX_MOVE_PX` movement, tracked via
  `panel.tapStart`) from a drag/pinch, and a tap calls `selectPoint()`,
  which sets `state.pinned = true` and freezes the tooltip/crosshair at that
  point -- `handleHover()` and the `pointerleave` handler both check
  `state.pinned` first and no-op while it's set, so plain mouse movement
  afterward doesn't overwrite it. Dismissed by: tapping/clicking elsewhere
  on the *same* chart (moves the pin), a document-level `pointerdown`
  listener outside `.chart-card` (clears it), or "Reset view". A
  `pointercancel` (browser took the gesture over, e.g. a page scroll) is
  deliberately *not* treated as a tap -- only a genuine `pointerup` is.
  `showReadingsAt()` (in `handleHover`/`selectPoint`) must check *both* a
  region's `history` and `projection` arrays for the nearest point, not just
  `history` -- projection points are PSI-only (no `pm25_1h`), tagged in the
  tooltip row with `projected: true` and rendered as "PSI ~NN" with a
  "(proj.)" region suffix, no PM value. Forgetting the projection array here
  was an actual bug: tapping anywhere along the dashed projected-PSI line
  just kept showing the nearest *actual* reading (barely changing), since
  `history` has nothing out there to match against.
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
