"""Builds docs/data.json (the numbers) + docs/index.html (a static page
that renders them as an interactive SVG chart -- drag to pan, scroll/pinch
to zoom, both the time-series PM2.5 and PSI panels for Singapore's five
real reporting regions (north/south/east/west/central), with a flat-PM2.5
projection on the PSI panel extrapolating toward the 100/150/200/250
thresholds).

The page has two tabs: "Live dashboard" (built from docs/data.json, written
by this script) and "Past episodes" (built from docs/episodes/data.json,
written by scripts/build_episodes_page.py from a separate, independently
scheduled pipeline -- see fetch_episodes_data.py/build_episodes_page.py/
.github/workflows/haze-episodes.yml). The episodes tab's data is fetched
lazily, the first time that tab is opened.

Two stacked single-axis panels (PM2.5, then PSI) -- never one dual-axis
plot, which would invent a correlation between two differently-scaled
series. Each region gets a fixed categorical color (a validated
colorblind-safe order, never cycled), shared between both panels so a
region reads as the same color throughout.

index.html is static boilerplate (same bytes every run); only data.json
changes. All the chart math (projection, thresholds, breakpoints) stays in
Python/aq_lib -- the browser only renders and pans/zooms already-computed
numbers, it doesn't recompute anything.

CAVEATS (see aq_lib.py for the PSI-modeling one):
  - The projection assumes each region's latest 1-hr PM2.5 reading holds
    perfectly flat for up to 24h. Real air quality will not actually do
    this -- this is a simplification for a quick "if nothing changes"
    read, not a forecast.
"""
from __future__ import annotations

import csv
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from aq_lib import API_REGIONS, HISTORY_PATH, THRESHOLDS, compute_payload, psi_to_pm25  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("build_dashboard")

DOCS_DIR = "docs"
DATA_PATH = os.path.join(DOCS_DIR, "data.json")
HTML_PATH = os.path.join(DOCS_DIR, "index.html")

# Fixed categorical order -- the first five slots of a colorblind-validated
# eight-hue palette (worst adjacent CVD deltaE 9.1 light / 8.4 dark across
# the full eight; a fortiori across five). Assigned once per region and
# never reused/cycled/reordered by data. Kept in sync with docs/index.html's
# own copy (JS can't import Python constants).
REGION_COLORS = {
    "north": "#2a78d6",
    "south": "#eb6834",
    "east": "#1baf7a",
    "west": "#eda100",
    "central": "#e87ba4",
}


def load_all_rows() -> dict[str, list[dict]]:
    by_region: dict[str, list[dict]] = {r: [] for r in API_REGIONS}
    if not os.path.exists(HISTORY_PATH):
        raise SystemExit(f"{HISTORY_PATH} does not exist -- run scripts/fetch_data.py first")
    with open(HISTORY_PATH, newline="") as f:
        for row in csv.DictReader(f):
            if row["region"] in by_region:
                by_region[row["region"]].append(row)
    for rows in by_region.values():
        rows.sort(key=lambda r: r["timestamp"])
    return by_region


def main() -> None:
    by_region = load_all_rows()
    payloads = {}
    for region, rows in by_region.items():
        payload = compute_payload(rows, region)
        if payload is not None:
            payloads[region] = payload
        else:
            log.warning("no data for region=%s -- omitting from chart", region)

    if not payloads:
        raise SystemExit("no region had any data -- refusing to build an empty chart")

    os.makedirs(DOCS_DIR, exist_ok=True)

    # The PM2.5-equivalent of each PSI threshold, for reference lines on the
    # PM2.5 panel -- a single value per threshold, NOT per region. The
    # flat-hold projection fully replaces the 24h average by hour 24
    # (avg(24h) = X), so "what flat PM2.5 is needed to reach this PSI
    # within 24h" is a pure breakpoint-table conversion, independent of any
    # region's current baseline. Drawing it per region would just stack
    # identical lines on top of each other -- see the threshold-status
    # table (which *does* vary per region, via reachable/hours/eta) for
    # the number that actually differs.
    out = {
        "colors": REGION_COLORS,
        "pm25_thresholds": [{"psi": t, "pm25": round(psi_to_pm25(t), 1)} for t in THRESHOLDS],
        "regions": payloads,
    }
    with open(DATA_PATH, "w") as f:
        json.dump(out, f, indent=2)
    log.info("wrote %s (%d region(s))", DATA_PATH, len(payloads))

    write_html_once()

    # GitHub Pages runs a "Deploy from a branch" source through Jekyll by
    # default; .nojekyll tells it to serve docs/ as plain static files
    # instead (this isn't a Jekyll site, and the default build breaks on it).
    open(os.path.join(DOCS_DIR, ".nojekyll"), "a").close()


def write_html_once() -> None:
    """index.html has no per-run dynamic content (the page reads data.json
    itself at view-time) so this writes identical bytes every run -- cheap
    to call unconditionally, and git sees no diff when nothing about the
    page itself changed."""
    with open(HTML_PATH, "w") as f:
        f.write(INDEX_HTML)
    log.info("wrote %s", HTML_PATH)


INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Singapore Haze Dashboard</title>
<style>
  :root {
    color-scheme: light;
    --bg: #f9f9f7;
    --surface: #fcfcfb;
    --ink: #0b0b0b;
    --muted: #52514e;
    --faint: #898781;
    --grid: #e1e0d9;
    --border: rgba(11,11,11,0.10);
    --band: rgba(235,104,52,0.08);
    --whatif-line: #2a78d6;
    --whatif-band: rgba(42,120,214,0.12);
  }
  @media (prefers-color-scheme: dark) {
    :root {
      color-scheme: dark;
      --bg: #0d0d0d;
      --surface: #1a1a19;
      --ink: #ffffff;
      --muted: #c3c2b7;
      --faint: #898781;
      --grid: #2c2c2a;
      --border: rgba(255,255,255,0.10);
      --band: rgba(235,104,52,0.14);
      --whatif-line: #5b9bea;
      --whatif-band: rgba(91,155,234,0.18);
    }
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    background: var(--bg);
    color: var(--ink);
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  }
  main { max-width: 900px; margin: 0 auto; padding: 20px 16px 40px; }
  header { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
  h1 { font-size: 1.4rem; margin: 0 0 4px; }
  .subtitle { color: var(--muted); font-size: 0.9rem; margin: 0 0 12px; }
  .refresh-btn {
    flex: 0 0 auto;
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font: inherit;
    font-size: 0.8rem;
    padding: 5px 10px;
    border-radius: 6px;
    border: 1px solid var(--border);
    background: var(--surface);
    color: var(--ink);
    cursor: pointer;
  }
  .tabs { display: flex; gap: 4px; margin: 10px 0 14px; border-bottom: 1px solid var(--border); }
  .tab-btn {
    font: inherit;
    font-size: 0.85rem;
    padding: 8px 14px;
    border: none;
    background: none;
    color: var(--muted);
    cursor: pointer;
    border-bottom: 2px solid transparent;
    margin-bottom: -1px;
  }
  .tab-btn.active { color: var(--ink); font-weight: 600; border-bottom-color: var(--ink); }
  .toolbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    margin-bottom: 8px;
    font-size: 0.8rem;
    color: var(--muted);
  }
  .toolbar button {
    font: inherit;
    font-size: 0.8rem;
    padding: 5px 10px;
    border-radius: 6px;
    border: 1px solid var(--border);
    background: var(--surface);
    color: var(--ink);
    cursor: pointer;
  }
  .legend {
    display: flex;
    flex-wrap: wrap;
    gap: 14px;
    font-size: 0.82rem;
    color: var(--muted);
    margin: 4px 0 10px;
  }
  .legend .key { display: inline-flex; align-items: center; gap: 5px; }
  .legend .swatch { width: 14px; height: 3px; border-radius: 2px; display: inline-block; }
  .region-filter { display: flex; flex-wrap: wrap; gap: 6px; margin: 4px 0 10px; }
  .region-filter button {
    font: inherit;
    font-size: 0.78rem;
    padding: 4px 11px;
    border-radius: 999px;
    border: 1px solid var(--border);
    background: var(--surface);
    color: var(--muted);
    cursor: pointer;
  }
  .region-filter button.active { background: var(--ink); color: var(--bg); border-color: var(--ink); }
  .picker-row { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin: 4px 0 10px; }
  .picker-row label { font-size: 0.82rem; color: var(--muted); }
  select#episode-select {
    font: inherit;
    font-size: 0.85rem;
    padding: 6px 8px;
    border-radius: 6px;
    border: 1px solid var(--border);
    background: var(--surface);
    color: var(--ink);
    flex: 1 1 auto;
    min-width: 0;
  }
  .episode-meta { font-size: 0.82rem; color: var(--muted); margin: 4px 0 10px; line-height: 1.5; }
  .episode-meta strong { color: var(--ink); }
  .whatif-form {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 10px 16px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 12px 14px;
    margin: 4px 0 10px;
  }
  .whatif-row { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
  .whatif-row label { font-size: 0.82rem; color: var(--muted); min-width: 170px; }
  .whatif-row .whatif-dash { color: var(--faint); }
  .whatif-form input[type="number"] {
    font: inherit;
    font-size: 0.85rem;
    padding: 6px 8px;
    border-radius: 6px;
    border: 1px solid var(--border);
    background: var(--bg);
    color: var(--ink);
    width: 80px;
  }
  .whatif-form button {
    font: inherit;
    font-size: 0.85rem;
    padding: 7px 16px;
    border-radius: 6px;
    border: 1px solid var(--border);
    background: var(--ink);
    color: var(--bg);
    cursor: pointer;
    font-weight: 600;
  }
  #whatif-error { color: #c0392b; }
  .chart-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 10px 12px 4px;
  }
  .panel-title { font-size: 0.85rem; color: var(--muted); text-align: center; margin: 2px 0 4px; }
  .status-card { margin-top: 14px; }
  .status-card .table-wrap { max-height: none; }
  .status-note { margin: 8px 2px 2px; font-size: 0.76rem; color: var(--muted); line-height: 1.4; }
  td.status-ok { font-variant-numeric: tabular-nums; }
  td.status-none { color: var(--faint); }
  svg.chart {
    width: 100%; height: auto; display: block; touch-action: none; cursor: grab;
    user-select: none; -webkit-user-select: none;
  }
  svg.chart.dragging { cursor: grabbing; }
  .axis-label { font-size: 10px; fill: var(--faint); }
  .threshold-label { font-size: 10px; fill: var(--muted); }
  .tooltip {
    position: fixed;
    pointer-events: none;
    background: var(--ink);
    color: var(--bg);
    font-size: 0.78rem;
    padding: 6px 9px;
    border-radius: 6px;
    line-height: 1.5;
    z-index: 20;
    white-space: nowrap;
  }
  .tooltip .row { display: flex; gap: 10px; justify-content: space-between; }
  .tooltip .row .k { opacity: 0.75; }
  .tooltip .row .v { font-weight: 600; font-variant-numeric: tabular-nums; }
  .tooltip .tooltip-actions {
    pointer-events: auto;
    gap: 6px;
    margin-top: 6px;
    padding-top: 6px;
    border-top: 1px solid rgba(255,255,255,0.2);
  }
  .tooltip .tooltip-actions button {
    font: inherit;
    font-size: 0.72rem;
    padding: 4px 8px;
    border-radius: 5px;
    border: 1px solid rgba(255,255,255,0.3);
    background: transparent;
    color: inherit;
    cursor: pointer;
  }
  .table-section { margin-top: 10px; }
  .table-section button {
    font: inherit;
    font-size: 0.85rem;
    padding: 6px 12px;
    border-radius: 6px;
    border: 1px solid var(--border);
    background: var(--surface);
    color: var(--ink);
    cursor: pointer;
  }
  .table-wrap { margin-top: 10px; max-height: 340px; overflow: auto; border: 1px solid var(--border); border-radius: 10px; }
  table.data-table { width: 100%; border-collapse: collapse; font-size: 0.78rem; background: var(--surface); }
  table.data-table th, table.data-table td {
    text-align: right; padding: 5px 9px; border-bottom: 1px solid var(--grid);
    font-variant-numeric: tabular-nums; white-space: nowrap;
  }
  table.data-table th:first-child, table.data-table td:first-child,
  table.data-table th:nth-child(2), table.data-table td:nth-child(2) { text-align: left; }
  table.data-table thead th { position: sticky; top: 0; background: var(--surface); color: var(--muted); font-variant-numeric: normal; }
  footer { margin-top: 16px; font-size: 0.78rem; color: var(--muted); line-height: 1.5; }
  .empty-state { color: var(--muted); font-size: 0.9rem; padding: 24px 0; text-align: center; }
</style>
</head>
<body>
<main>
  <header>
    <div>
      <h1>Singapore Haze Dashboard</h1>
      <p class="subtitle" id="subtitle">Loading&hellip;</p>
    </div>
    <button class="refresh-btn" id="refresh-page" type="button" title="Reload the page to fetch the latest data">&#8635; Refresh</button>
  </header>

  <div class="tabs" role="tablist">
    <button class="tab-btn active" id="tab-btn-live" type="button" role="tab" aria-selected="true">Live dashboard</button>
    <button class="tab-btn" id="tab-btn-episodes" type="button" role="tab" aria-selected="false">Past episodes</button>
    <button class="tab-btn" id="tab-btn-h15" type="button" role="tab" aria-selected="false">2015 Haze</button>
    <button class="tab-btn" id="tab-btn-whatif" type="button" role="tab" aria-selected="false">What-if Projection</button>
  </div>

  <div id="tab-panel-live">
    <div class="toolbar">
      <span>Drag to pan &middot; scroll or pinch to zoom &middot; tap a point for readings</span>
      <button id="reset-view" type="button">Reset view</button>
    </div>

    <div class="legend" id="legend"></div>

    <div class="chart-card">
      <div class="panel-title">PM2.5 (&micro;g/m&sup3;, 1-hr) &mdash; grey lines mark the level that would push 24-hr PSI to 100/150/200/250</div>
      <svg class="chart" id="chart-pm25"></svg>
      <div class="panel-title">PSI (24-hr) &mdash; solid = actual, dashed = projected (flat 1-hr PM2.5 held constant)</div>
      <svg class="chart" id="chart-psi"></svg>
    </div>

    <div class="chart-card status-card">
      <div class="panel-title">Threshold status &mdash; projected over the next 24h</div>
      <div class="table-wrap">
        <table class="data-table" id="status-table">
          <thead>
            <tr><th>Region</th><th>PSI now</th><th>&rarr; 100</th><th>&rarr; 150</th><th>&rarr; 200</th><th>&rarr; 250</th></tr>
          </thead>
          <tbody id="status-table-body"></tbody>
        </table>
      </div>
      <p class="status-note">&ndash; means not on track to cross that threshold within 24h at today's current 1-hr reading (see the dashed PSI projection above for the trend); N/A means the current PSI is already at or above it.</p>
    </div>

    <div class="table-section">
      <button id="toggle-table" type="button">View data table</button>
      <div class="table-wrap" id="table-wrap" hidden>
        <table class="data-table" id="data-table">
          <thead>
            <tr><th>Time (SGT)</th><th>Region</th><th>PSI</th><th>PM2.5 1h</th><th>PM2.5 24h</th><th>Source</th></tr>
          </thead>
          <tbody id="data-table-body"></tbody>
        </table>
      </div>
    </div>
  </div>

  <div id="tab-panel-episodes" hidden>
    <p class="subtitle" id="subtitle-epi">Loading&hellip;</p>

    <div class="region-filter" id="region-filter-epi" role="group" aria-label="Filter episodes by region"></div>

    <div class="picker-row">
      <label for="episode-select">Episode</label>
      <select id="episode-select"></select>
    </div>
    <p class="episode-meta" id="episode-meta"></p>

    <div class="toolbar">
      <span>Drag to pan &middot; scroll or pinch to zoom &middot; tap a point for readings</span>
      <button id="reset-view-epi" type="button">Reset view</button>
    </div>

    <div class="chart-card" id="chart-card-epi">
      <div class="panel-title">PM2.5 (&micro;g/m&sup3;, 1-hr)</div>
      <svg class="chart" id="chart-pm25-epi"></svg>
      <div class="panel-title">PSI (24-hr) &mdash; shaded band marks the episode itself (above the threshold)</div>
      <svg class="chart" id="chart-psi-epi"></svg>
    </div>

    <div class="table-section">
      <button id="toggle-table-epi" type="button">View data table</button>
      <div class="table-wrap" id="table-wrap-epi" hidden>
        <table class="data-table" id="data-table-epi">
          <thead><tr><th>Time (SGT)</th><th>PSI</th><th>PM2.5 1h</th></tr></thead>
          <tbody id="data-table-body-epi"></tbody>
        </table>
      </div>
    </div>
  </div>

  <div id="tab-panel-h15" hidden>
    <p class="subtitle" id="subtitle-h15">Loading&hellip;</p>

    <div class="toolbar">
      <span>Drag to pan &middot; scroll or pinch to zoom &middot; tap a point for readings</span>
      <button id="reset-view-h15" type="button">Reset view</button>
    </div>

    <div class="legend" id="legend-h15"></div>

    <div class="chart-card" id="chart-card-h15">
      <div class="panel-title">PM2.5 (&micro;g/m&sup3;, 1-hr)</div>
      <svg class="chart" id="chart-pm25-h15"></svg>
      <div class="panel-title">PSI (24-hr)</div>
      <svg class="chart" id="chart-psi-h15"></svg>
    </div>

    <div class="table-section">
      <button id="toggle-table-h15" type="button">View data table</button>
      <div class="table-wrap" id="table-wrap-h15" hidden>
        <table class="data-table" id="data-table-h15">
          <thead>
            <tr><th>Time (SGT)</th><th>Region</th><th>PSI</th><th>PM2.5 1h</th></tr>
          </thead>
          <tbody id="data-table-body-h15"></tbody>
        </table>
      </div>
    </div>
  </div>

  <div id="tab-panel-whatif" hidden>
    <p class="subtitle" id="subtitle-whatif">Loading&hellip;</p>

    <div class="whatif-form" id="whatif-form">
      <div class="whatif-row">
        <label for="whatif-psi-low">24-hr PSI range</label>
        <input type="number" id="whatif-psi-low" step="1" min="0" inputmode="decimal">
        <span class="whatif-dash">&ndash;</span>
        <input type="number" id="whatif-psi-high" step="1" min="0" inputmode="decimal">
      </div>
      <div class="whatif-row">
        <label for="whatif-pm-low">Expected 1-hr PM2.5 range (&micro;g/m&sup3;)</label>
        <input type="number" id="whatif-pm-low" step="0.1" min="0" inputmode="decimal">
        <span class="whatif-dash">&ndash;</span>
        <input type="number" id="whatif-pm-high" step="0.1" min="0" inputmode="decimal">
      </div>
      <button id="whatif-submit" type="button">Calculate</button>
    </div>
    <p class="status-note" id="whatif-error" hidden></p>

    <div class="toolbar">
      <span>Drag to pan &middot; scroll or pinch to zoom &middot; tap a point, then "Edit low/high" to inject a new value from there onward</span>
      <button id="reset-view-whatif" type="button">Reset view</button>
    </div>

    <div class="chart-card" id="chart-card-whatif">
      <div class="panel-title">PM2.5 (&micro;g/m&sup3;, 1-hr) &mdash; the flat value assumed from each point onward; steps immediately at an injection (the PSI below is its 24-hr rolling average, so it catches up over 24h instead)</div>
      <svg class="chart" id="chart-pm25-whatif"></svg>
      <div class="panel-title">PSI (24-hr) &mdash; projected hourly over the next 3 days (through the end of that final day), holding the entered 1-hr PM2.5 range flat</div>
      <svg class="chart" id="chart-psi-whatif"></svg>
    </div>

    <div class="table-section">
      <button id="toggle-table-whatif" type="button">View data table</button>
      <div class="table-wrap" id="table-wrap-whatif" hidden>
        <table class="data-table" id="data-table-whatif">
          <thead><tr><th>Time (SGT)</th><th>PM2.5 1h (low)</th><th>PM2.5 1h (high)</th><th>PSI (low)</th><th>PSI (high)</th></tr></thead>
          <tbody id="data-table-body-whatif"></tbody>
        </table>
      </div>
    </div>
  </div>

  <footer>
    Model note: PSI here tracks only the PM2.5 sub-index (real PSI = max of six pollutant
    sub-indices: PM2.5, PM10, SO2, CO, O3, NO2), so on a day another pollutant dominates the
    real PSI can read higher than shown here. The dashed projection on the Live dashboard tab
    assumes each region's latest 1-hr PM2.5 reading holds perfectly flat for up to 24h -- a
    simplification for a quick "if nothing changes" read, not a forecast. An episode (Past
    episodes tab) is a contiguous stretch where a region's 24-hr PSI was above the threshold
    shown there; each chart pads 24h before/after for context. The 2015 Haze tab shows actual
    readings only (no projection) from NEA's historical PM2.5/PSI datasets, 1 Jun&ndash;30 Nov
    2015. The What-if Projection tab uses the same flat-hold model as the Live dashboard, but
    lets you enter your own 24-hr PSI and 1-hr PM2.5 ranges instead of using live readings --
    the low/high band is just that model run once at each end of your two ranges, not a formal
    confidence interval. Tap a point on that chart and use its "Edit low/high" buttons to inject
    a new PM2.5 value partway through -- everything after that hour recalculates from it, as its
    own fresh flat-hold run; everything before stays as already drawn. Calculate re-runs from the
    form and clears any injections. Data: data.gov.sg.
  </footer>
</main>

<div class="tooltip" id="tooltip" hidden></div>

<script>
(function () {
  "use strict";

  // ---------------------------------------------------------------------
  // Shared constants + stateless helpers -- used by both the live
  // dashboard tab ("state") and the past-episodes tab ("estate").
  // ---------------------------------------------------------------------
  var SG_TZ = "Asia/Singapore";
  var SG_OFFSET_MS = 8 * 3600 * 1000;
  var THRESHOLDS = [100, 150, 200, 250];
  var MARGIN = { top: 10, right: 60, bottom: 6, left: 44 };
  var BOTTOM_AXIS_H = 24;
  var H_PM25 = 220, H_PSI = 250;
  var MIN_SPAN_MS = 3 * 3600 * 1000; // can't zoom in tighter than 3h
  var TAP_MAX_MOVE_PX = 8; // pointerdown->up movement under this counts as a tap, not a drag
  var ONE_DAY_MS = 24 * 3600 * 1000;
  var MAX_MARKER_POINTS = 60; // per line, within the current view -- above this, dots would just be a smear
  // The live dashboard retains/can show up to HISTORY_WINDOW_HOURS (60
  // days, see aq_lib.py) of history, but starting zoomed out that far
  // makes the initial view cluttered and hard to read. Default (and
  // "Reset view") to the most recent 48h instead -- the full range is
  // still just a pan/zoom away.
  var DEFAULT_VIEW_MS = 48 * 3600 * 1000;
  var MIN_PX_PER_TICK = 65;
  var STEP_CANDIDATES_MS = [15, 30, 60, 120, 180, 360, 720, 1440, 2880, 4320, 10080, 20160, 43200, 86400]
    .map(function (m) { return m * 60 * 1000; });

  var els = {};
  var activeTab = "live";

  function debounce(fn, ms) {
    var t;
    return function () {
      clearTimeout(t);
      var args = arguments;
      t = setTimeout(function () { fn.apply(null, args); }, ms);
    };
  }

  function fmtSGT(ms, opts) {
    return new Intl.DateTimeFormat("en-GB", Object.assign({
      timeZone: SG_TZ, weekday: "short", hour: "2-digit", minute: "2-digit", hour12: false
    }, opts || {})).format(new Date(ms));
  }

  // en-CA formats numeric year/month/day as YYYY-MM-DD directly -- used for
  // x-axis ticks at day-or-coarser zoom (see renderPanel), where showing a
  // weekday+time label would either repeat the same date across every tick
  // (misleading) or just be less scannable than a plain ISO date.
  function fmtAxisDate(ms) {
    return new Intl.DateTimeFormat("en-CA", {
      timeZone: SG_TZ, year: "numeric", month: "2-digit", day: "2-digit"
    }).format(new Date(ms));
  }

  // "YYYY-MM-DD HH:MM" -- used on the Past episodes tab, where dates span
  // weeks/months apart and a plain ISO date + 24h time is quicker to scan
  // and compare than a weekday-relative label.
  function fmtDateTime(ms) {
    return fmtAxisDate(ms) + " " + new Intl.DateTimeFormat("en-GB", {
      timeZone: SG_TZ, hour: "2-digit", minute: "2-digit", hour12: false
    }).format(new Date(ms));
  }

  function capitalize(s) { return s.charAt(0).toUpperCase() + s.slice(1); }

  // 24-hr avg PM2.5 (ug/m3) <-> PSI breakpoints + flat-hold projection math,
  // ported from aq_lib.py (PM25_PSI_BREAKPOINTS / pm25_to_psi / psi_to_pm25 /
  // projected_avg_pm25) for the What-if Projection tab, which computes
  // entirely client-side from user-entered numbers rather than precomputed
  // server-side values -- keep these two copies in sync by hand.
  var PM25_PSI_BREAKPOINTS = [
    [0.0, 0], [12.0, 50], [55.4, 100], [150.4, 200], [250.4, 300], [350.4, 400], [500.4, 500]
  ];

  function interpLin(x, x0, x1, y0, y1) {
    if (x1 === x0) return y0;
    return y0 + (x - x0) * (y1 - y0) / (x1 - x0);
  }

  function pm25ToPsi(pm25) {
    if (pm25 <= 0) return 0;
    var pts = PM25_PSI_BREAKPOINTS;
    if (pm25 >= pts[pts.length - 1][0]) {
      var a = pts[pts.length - 2], b = pts[pts.length - 1];
      return interpLin(pm25, a[0], b[0], a[1], b[1]);
    }
    for (var i = 0; i < pts.length - 1; i++) {
      var x0 = pts[i][0], y0 = pts[i][1], x1 = pts[i + 1][0], y1 = pts[i + 1][1];
      if (x0 <= pm25 && pm25 <= x1) return interpLin(pm25, x0, x1, y0, y1);
    }
    return pts[pts.length - 1][1];
  }

  function psiToPm25(psi) {
    if (psi <= 0) return 0;
    var pts = PM25_PSI_BREAKPOINTS;
    if (psi >= pts[pts.length - 1][1]) {
      var a = pts[pts.length - 2], b = pts[pts.length - 1];
      return interpLin(psi, a[1], b[1], a[0], b[0]);
    }
    for (var i = 0; i < pts.length - 1; i++) {
      var x0 = pts[i][0], y0 = pts[i][1], x1 = pts[i + 1][0], y1 = pts[i + 1][1];
      if (y0 <= psi && psi <= y1) return interpLin(psi, y0, y1, x0, x1);
    }
    return pts[pts.length - 1][0];
  }

  // Projected 24-hr avg PM2.5 at t hours ahead, holding the "latest" 1-hr
  // reading flat and linearly displacing the 24-hr window -- identical to
  // aq_lib.projected_avg_pm25. Past t=24 the whole window is the flat
  // value, so callers just use `latest` directly for t > 24.
  function projectedAvgPm25(baseline, latest, tHours) {
    var t = Math.max(0, Math.min(24, tHours));
    return ((24 - t) * baseline + t * latest) / 24;
  }

  function niceTicks(min, max, count) {
    if (min === max) { min -= 1; max += 1; }
    var span = max - min;
    var step0 = span / count;
    var mag = Math.pow(10, Math.floor(Math.log10(step0)));
    var residual = step0 / mag;
    var step = residual > 5 ? 10 * mag : residual > 2 ? 5 * mag : residual > 1 ? 2 * mag : mag;
    var niceMin = Math.floor(min / step) * step;
    var niceMax = Math.ceil(max / step) * step;
    var ticks = [];
    for (var v = niceMin; v <= niceMax + 1e-9; v += step) ticks.push(Math.round(v * 1000) / 1000);
    return ticks;
  }

  // Time-tick step, chosen so ticks fit the *actual* available width
  // (narrow mobile screens need fewer ticks or "Sat 12:00"-style labels
  // collide into illegible mush) -- aligned to nice SGT-hour boundaries
  // (not UTC/epoch ones -- otherwise ticks land on odd times). Extends up
  // to a 60-day step so a fully-zoomed-out live view (up to 60 days of
  // history) doesn't pack in far more ticks than maxTicks allows.
  function timeTicks(domain, innerW) {
    var span = domain[1] - domain[0];
    var maxTicks = Math.max(2, Math.floor(innerW / MIN_PX_PER_TICK));
    var step = STEP_CANDIDATES_MS[STEP_CANDIDATES_MS.length - 1];
    for (var i = 0; i < STEP_CANDIDATES_MS.length; i++) {
      if (span / STEP_CANDIDATES_MS[i] <= maxTicks) { step = STEP_CANDIDATES_MS[i]; break; }
    }
    var startLocal = domain[0] + SG_OFFSET_MS;
    var first = Math.ceil(startLocal / step) * step - SG_OFFSET_MS;
    var ticks = [];
    for (var t = first; t <= domain[1]; t += step) ticks.push(t);
    return { ticks: ticks, stepMs: step };
  }

  function scaleLinear(domain, range) {
    var d0 = domain[0], d1 = domain[1], r0 = range[0], r1 = range[1];
    var span = d1 - d0 || 1;
    return function (v) { return r0 + ((v - d0) / span) * (r1 - r0); };
  }

  function svgEl(tag, attrs) {
    var el = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (var k in attrs) el.setAttribute(k, attrs[k]);
    return el;
  }

  function linePath(points, x, y, xField, yField) {
    var d = "", pen = false;
    points.forEach(function (p) {
      var v = p[yField];
      if (v === null || v === undefined) { pen = false; return; }
      var cmd = pen ? "L" : "M";
      d += cmd + x(p[xField]).toFixed(1) + "," + y(v).toFixed(1) + " ";
      pen = true;
    });
    return d.trim();
  }

  function drawMarkers(container, points, x, y, xField, yField, color, opacity) {
    var op = opacity === undefined ? 1 : opacity;
    points.forEach(function (p) {
      var v = p[yField];
      if (v === null || v === undefined) return;
      container.appendChild(svgEl("circle", {
        cx: x(p[xField]).toFixed(1), cy: y(v).toFixed(1), r: 2.5, fill: color, opacity: op
      }));
    });
  }

  function appendCell(tr, text, className) {
    var td = document.createElement("td");
    td.textContent = text;
    if (className) td.className = className;
    tr.appendChild(td);
  }

  function panelHeight(isPsi) { return isPsi ? H_PSI : H_PM25; }
  function panelInnerH(isPsi) {
    return panelHeight(isPsi) - MARGIN.top - MARGIN.bottom - (isPsi ? BOTTOM_AXIS_H : 0);
  }

  function buildPanelGeneric(id, isPsi, panelsArray, attachFn) {
    var svg = document.getElementById(id);
    var g = svgEl("g");
    svg.appendChild(g);

    var clipId = id + "-clip";
    var defs = svgEl("defs");
    var clipRect = svgEl("rect");
    var clipPath = svgEl("clipPath", { id: clipId });
    clipPath.appendChild(clipRect);
    defs.appendChild(clipPath);
    svg.appendChild(defs);

    // Fixed draw order so a full rebuild each render never needs fragile
    // child-index bookkeeping: grid (bottom) -> plot (clipped, middle) ->
    // chrome (ticks/labels/crosshair, top).
    var gridGroup = svgEl("g");
    var plot = svgEl("g", { "clip-path": "url(#" + clipId + ")" });
    var chromeGroup = svgEl("g");
    g.appendChild(gridGroup);
    g.appendChild(plot);
    g.appendChild(chromeGroup);

    var panel = {
      svg: svg, g: g, gridGroup: gridGroup, plot: plot, chromeGroup: chromeGroup,
      clipRect: clipRect, isPsi: isPsi, id: id
    };
    panelsArray.push(panel);
    attachFn(panel);
    return panel;
  }

  // ---------------------------------------------------------------------
  // Live dashboard tab
  // ---------------------------------------------------------------------
  var state = {
    data: null,
    fullDomain: null,   // [minMs, maxMs] across all real data
    viewDomain: null,   // currently visible [minMs, maxMs], within fullDomain
    pm25YDomain: null,
    psiYDomain: null,
    panels: [],         // {svg, g, gridGroup, plot, chromeGroup, innerW, innerH, isPsi}
    width: 860,
    pinned: false,      // true once a tap/click has pinned the readings tooltip in place
  };

  function measureWidth() {
    var card = document.querySelector("#tab-panel-live .chart-card");
    state.width = Math.max(280, card.clientWidth - 24);
  }

  function buildLegend(colors) {
    els.legend.innerHTML = "";
    Object.keys(colors).forEach(function (region) {
      var span = document.createElement("span");
      span.className = "key";
      var sw = document.createElement("span");
      sw.className = "swatch";
      sw.style.background = colors[region];
      var label = document.createElement("span");
      label.textContent = capitalize(region);
      span.appendChild(sw);
      span.appendChild(label);
      els.legend.appendChild(span);
    });
  }

  function computeYDomains() {
    // Padding the PM2.5 axis out to cover every pm25_thresholds value (not
    // just the actual data) mirrors how the PSI axis already pads out to
    // THRESHOLDS -- so the "what PM2.5 would push PSI to 100/150/200/250"
    // reference lines are always visible, not just once a region's
    // readings happen to climb into range.
    var pm25ThresholdVals = (state.data.pm25_thresholds || []).map(function (t) { return t.pm25; });
    var pm25Vals = [0].concat(pm25ThresholdVals), psiVals = [0].concat(THRESHOLDS);
    Object.keys(state.data.regions).forEach(function (region) {
      var p = state.data.regions[region];
      p.history.forEach(function (h) {
        if (h.pm25_1h !== null) pm25Vals.push(h.pm25_1h);
        if (h.psi !== null) psiVals.push(h.psi);
      });
      p.projection.forEach(function (pt) { psiVals.push(pt.psi); });
    });
    var pm25Ticks = niceTicks(Math.min.apply(null, pm25Vals), Math.max.apply(null, pm25Vals), 4);
    var psiTicks = niceTicks(Math.min.apply(null, psiVals), Math.max.apply(null, psiVals), 4);
    state.pm25YDomain = [pm25Ticks[0], pm25Ticks[pm25Ticks.length - 1]];
    state.psiYDomain = [psiTicks[0], psiTicks[psiTicks.length - 1]];
  }

  function buildPanel(id, isPsi) { return buildPanelGeneric(id, isPsi, state.panels, attachInteraction); }

  function renderAll() {
    if (!state.data) return;
    state.panels.forEach(renderPanel);
  }

  function renderPanel(panel) {
    var W = state.width, H = panelHeight(panel.isPsi);
    var innerW = W - MARGIN.left - MARGIN.right;
    var innerH = panelInnerH(panel.isPsi);

    panel.svg.setAttribute("viewBox", "0 0 " + W + " " + H);
    panel.svg.setAttribute("width", W);
    panel.svg.setAttribute("height", H);
    panel.g.setAttribute("transform", "translate(" + MARGIN.left + "," + MARGIN.top + ")");
    panel.clipRect.setAttribute("x", -2);
    panel.clipRect.setAttribute("y", -2);
    panel.clipRect.setAttribute("width", innerW + 4);
    panel.clipRect.setAttribute("height", innerH + 4);

    panel.gridGroup.innerHTML = "";
    panel.plot.innerHTML = "";
    panel.chromeGroup.innerHTML = "";

    var x = scaleLinear(state.viewDomain, [0, innerW]);
    var yDomain = panel.isPsi ? state.psiYDomain : state.pm25YDomain;
    var y = scaleLinear(yDomain, [innerH, 0]);
    panel.x = x; panel.y = y; panel.innerW = innerW; panel.innerH = innerH;

    var yTicks = niceTicks(yDomain[0], yDomain[1], 4);
    yTicks.forEach(function (t) {
      panel.gridGroup.appendChild(svgEl("line", { x1: 0, x2: innerW, y1: y(t), y2: y(t), stroke: "var(--grid)", "stroke-width": 1 }));
      var lbl = svgEl("text", { class: "axis-label", x: -6, y: y(t) + 3, "text-anchor": "end" });
      lbl.textContent = Math.round(t);
      panel.chromeGroup.appendChild(lbl);
    });

    var timeTickInfo = timeTicks(state.viewDomain, innerW);
    var useDateTicks = timeTickInfo.stepMs >= ONE_DAY_MS;
    timeTickInfo.ticks.forEach(function (t) {
      var xp = x(t);
      panel.gridGroup.appendChild(svgEl("line", { x1: xp, x2: xp, y1: 0, y2: innerH, stroke: "var(--grid)", "stroke-width": 1 }));
      if (panel.isPsi) {
        panel.chromeGroup.appendChild(svgEl("line", { x1: xp, x2: xp, y1: innerH, y2: innerH + 4, stroke: "var(--faint)", "stroke-width": 1 }));
        var lbl = svgEl("text", { class: "axis-label", x: xp, y: innerH + 15, "text-anchor": "middle" });
        lbl.textContent = useDateTicks ? fmtAxisDate(t) : fmtSGT(t);
        panel.chromeGroup.appendChild(lbl);
      }
    });

    var colors = state.data.colors;
    var regions = Object.keys(state.data.regions);

    if (panel.isPsi) {
      THRESHOLDS.forEach(function (th) {
        if (th < yDomain[0] || th > yDomain[1]) return;
        panel.plot.appendChild(svgEl("line", { x1: 0, x2: innerW, y1: y(th), y2: y(th), stroke: "var(--faint)", "stroke-width": 1 }));
        var lbl = svgEl("text", { class: "threshold-label", x: innerW - 2, y: y(th) - 3, "text-anchor": "end" });
        lbl.textContent = "PSI " + th;
        panel.chromeGroup.appendChild(lbl);
      });
    } else if (state.data.pm25_thresholds) {
      // The PM2.5 level each PSI threshold corresponds to -- a single
      // reference value per threshold (not per region, see pm25_thresholds
      // in build_dashboard.py for why). computeYDomains() already pads the
      // PM2.5 axis out to cover every one of these, so the in-range check
      // here is just a defensive no-op in the normal case, not what keeps
      // them visible.
      state.data.pm25_thresholds.forEach(function (pt) {
        if (pt.pm25 < yDomain[0] || pt.pm25 > yDomain[1]) return;
        panel.plot.appendChild(svgEl("line", { x1: 0, x2: innerW, y1: y(pt.pm25), y2: y(pt.pm25), stroke: "var(--faint)", "stroke-width": 1 }));
        var lbl = svgEl("text", { class: "threshold-label", x: innerW - 2, y: y(pt.pm25) - 3, "text-anchor": "end" });
        lbl.textContent = "→ PSI " + pt.psi;
        panel.chromeGroup.appendChild(lbl);
      });
    }

    regions.forEach(function (region) {
      var payload = state.data.regions[region];
      var color = colors[region];
      var hist = payload.history.map(function (h) { return { t: Date.parse(h.t), psi: h.psi, pm25_1h: h.pm25_1h }; });
      var field = panel.isPsi ? "psi" : "pm25_1h";
      var path = svgEl("path", {
        d: linePath(hist, x, y, "t", field), fill: "none", stroke: color,
        "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round"
      });
      panel.plot.appendChild(path);

      // Scatter markers on top of the line -- but only once a point's
      // neighbors are far enough apart to read as points rather than a
      // solid smear. 5 regions x many days of hourly data is a lot of
      // points fully zoomed out; drawing markers for all of that would
      // just be clutter, so gate on the *visible* (in the current
      // pan/zoom) point count, not the dataset size.
      if (countInView(hist, "t") <= MAX_MARKER_POINTS) {
        drawMarkers(panel.plot, hist, x, y, "t", field, color, 1);
      }

      if (panel.isPsi && payload.projection.length) {
        var proj = payload.projection.map(function (p) { return { t: Date.parse(p.t), psi: p.psi }; });
        var projPath = svgEl("path", {
          d: linePath(proj, x, y, "t", "psi"), fill: "none", stroke: color,
          "stroke-width": 2, "stroke-dasharray": "6 4", opacity: "0.6", "stroke-linecap": "round"
        });
        panel.plot.appendChild(projPath);
        if (countInView(proj, "t") <= MAX_MARKER_POINTS) {
          drawMarkers(panel.plot, proj, x, y, "t", "psi", color, 0.6);
        }
      }
    });

    var crosshair = svgEl("line", { x1: -10, x2: -10, y1: 0, y2: innerH, stroke: "var(--faint)", "stroke-width": 1, visibility: "hidden" });
    panel.chromeGroup.appendChild(crosshair);
    panel.crosshair = crosshair;
  }

  function countInView(points, xField) {
    var lo = state.viewDomain[0], hi = state.viewDomain[1], n = 0;
    for (var i = 0; i < points.length; i++) {
      var t = points[i][xField];
      if (t >= lo && t <= hi) n++;
    }
    return n;
  }

  function defaultViewDomain() {
    var full = state.fullDomain;
    var hi = full[1];
    var lo = Math.max(full[0], hi - DEFAULT_VIEW_MS);
    return [lo, hi];
  }

  function clampViewDomain(domain) {
    var full = state.fullDomain;
    var span = Math.min(domain[1] - domain[0], full[1] - full[0]);
    span = Math.max(span, MIN_SPAN_MS);
    var lo = domain[0], hi = lo + span;
    if (lo < full[0]) { lo = full[0]; hi = lo + span; }
    if (hi > full[1]) { hi = full[1]; lo = hi - span; }
    return [lo, hi];
  }

  function localXFromClientX(svg, clientX) {
    var rect = svg.getBoundingClientRect();
    var scale = state.width / rect.width;
    return (clientX - rect.left) * scale - MARGIN.left;
  }

  function zoomAtLocalX(panel, localX, factor) {
    var frac = Math.max(0, Math.min(1, localX / panel.innerW));
    var cursorT = state.viewDomain[0] + frac * (state.viewDomain[1] - state.viewDomain[0]);
    var span = (state.viewDomain[1] - state.viewDomain[0]) * factor;
    var lo = cursorT - frac * span, hi = lo + span;
    state.viewDomain = clampViewDomain([lo, hi]);
    renderAll();
  }

  // Single pointer = pan (drag). Two pointers on the same panel = pinch-zoom,
  // anchored at their midpoint. Lifting one finger of a pinch continues as a
  // fresh pan from the remaining finger, matching native map/photo apps.
  function attachInteraction(panel) {
    var svg = panel.svg;
    var pointers = {}; // pointerId -> {x, y}
    var dragState = null; // {startX, startDomain}
    var pinchState = null; // {ids: [id, id], lastDist}

    function activeIds() { return Object.keys(pointers); }
    function distanceBetween(idA, idB) {
      var a = pointers[idA], b = pointers[idB];
      return Math.hypot(a.x - b.x, a.y - b.y);
    }
    function midpointX(idA, idB) {
      return (pointers[idA].x + pointers[idB].x) / 2;
    }

    svg.addEventListener("pointerdown", function (evt) {
      evt.preventDefault(); // otherwise a drag starting over an axis-label <text> triggers native text selection
      try { svg.setPointerCapture(evt.pointerId); } catch (e) { /* capture is a nice-to-have, not required for pan/pinch to work */ }
      pointers[evt.pointerId] = { x: evt.clientX, y: evt.clientY };
      var ids = activeIds();

      if (ids.length === 2) {
        dragState = null;
        pinchState = { ids: ids, lastDist: distanceBetween(ids[0], ids[1]) };
        svg.classList.remove("dragging");
        panel.tapStart = null;
      } else if (ids.length === 1) {
        pinchState = null;
        svg.classList.add("dragging");
        dragState = { startX: evt.clientX, startDomain: state.viewDomain.slice() };
        panel.tapStart = { x: evt.clientX, y: evt.clientY };
      }
      // 3rd+ simultaneous pointer (e.g. a resting palm): ignored, current gesture continues.
    });

    svg.addEventListener("pointermove", function (evt) {
      if (!(evt.pointerId in pointers)) { handleHover(panel, evt); return; }
      pointers[evt.pointerId] = { x: evt.clientX, y: evt.clientY };

      if (panel.tapStart && Math.hypot(evt.clientX - panel.tapStart.x, evt.clientY - panel.tapStart.y) > TAP_MAX_MOVE_PX) {
        panel.tapStart = null; // moved too far to still count as a tap -- it's a drag
      }

      if (pinchState) {
        evt.preventDefault();
        var ids = pinchState.ids;
        if (!(ids[0] in pointers) || !(ids[1] in pointers)) return;
        var dist = distanceBetween(ids[0], ids[1]);
        if (pinchState.lastDist > 0 && dist > 0) {
          zoomAtLocalX(panel, localXFromClientX(svg, midpointX(ids[0], ids[1])), pinchState.lastDist / dist);
        }
        pinchState.lastDist = dist;
        return;
      }

      if (dragState) {
        evt.preventDefault();
        var scale = state.width / svg.getBoundingClientRect().width;
        var pxPerMs = panel.innerW / (dragState.startDomain[1] - dragState.startDomain[0]);
        var dxPx = (evt.clientX - dragState.startX) * scale;
        var dtMs = dxPx / pxPerMs;
        state.viewDomain = clampViewDomain([dragState.startDomain[0] - dtMs, dragState.startDomain[1] - dtMs]);
        renderAll();
        return;
      }

      handleHover(panel, evt);
    });

    function endPointer(evt) {
      try { svg.releasePointerCapture(evt.pointerId); } catch (e) { /* already released */ }
      delete pointers[evt.pointerId];
      var ids = activeIds();
      // Only a real pointerup (not a cancel -- e.g. the browser took over for
      // a page scroll) with no leftover pointers and no pinch in play counts
      // as a tap: pin the readings tooltip at that point.
      var wasTap = evt.type === "pointerup" && !pinchState && panel.tapStart && ids.length === 0;

      if (pinchState) {
        if (ids.length < 2) {
          pinchState = null;
          if (ids.length === 1) {
            dragState = { startX: pointers[ids[0]].x, startDomain: state.viewDomain.slice() };
            svg.classList.add("dragging");
          } else {
            svg.classList.remove("dragging");
          }
        }
      } else if (dragState && ids.length === 0) {
        dragState = null;
        svg.classList.remove("dragging");
      }

      if (wasTap) {
        panel.tapStart = null;
        selectPoint(panel, evt);
      }
    }
    svg.addEventListener("pointerup", endPointer);
    svg.addEventListener("pointercancel", endPointer);
    svg.addEventListener("pointerleave", function () {
      // Pointer capture (set on pointerdown above) suppresses pointerleave
      // for an actively-dragging/pinching pointer, so reaching here means
      // this was just a hover, not a live gesture -- safe to hide the crosshair.
      // A pinned (tapped/clicked) tooltip stays until the next tap/click.
      if (state.pinned) return;
      state.panels.forEach(function (p) { if (p.crosshair) p.crosshair.setAttribute("visibility", "hidden"); });
      els.tooltip.hidden = true;
    });

    svg.addEventListener("wheel", function (evt) {
      evt.preventDefault();
      var factor = evt.deltaY > 0 ? 1.15 : 1 / 1.15;
      zoomAtLocalX(panel, localXFromClientX(svg, evt.clientX), factor);
    }, { passive: false });
  }

  function handleHover(panel, evt) {
    if (state.pinned) return; // a tapped/clicked point holds the tooltip until dismissed
    showReadingsAt(tMsFromClientX(panel, evt.clientX), evt);
  }

  // A tap/click (as opposed to a drag/pinch, see attachInteraction) pins the
  // readings tooltip at that point instead of it just following the pointer
  // -- this is the only way to see readings on touch (no hover there), and
  // on desktop it freezes the tooltip in place instead of it disappearing
  // once the mouse moves off the chart.
  function selectPoint(panel, evt) {
    state.pinned = true;
    showReadingsAt(tMsFromClientX(panel, evt.clientX), evt);
  }

  function tMsFromClientX(panel, clientX) {
    var localX = localXFromClientX(panel.svg, clientX);
    var clampedX = Math.max(0, Math.min(panel.innerW, localX));
    return state.viewDomain[0] + (clampedX / panel.innerW) * (state.viewDomain[1] - state.viewDomain[0]);
  }

  function showReadingsAt(tMs, evt) {
    state.panels.forEach(function (p) {
      var cx = p.x ? p.x(tMs) : -10;
      if (p.crosshair) {
        p.crosshair.setAttribute("x1", cx);
        p.crosshair.setAttribute("x2", cx);
        p.crosshair.setAttribute("visibility", "visible");
      }
    });

    var rows = [];
    var regions = Object.keys(state.data.regions);
    regions.forEach(function (region) {
      var payload = state.data.regions[region];
      var nearest = null, bestDiff = Infinity, projected = false;
      payload.history.forEach(function (h) {
        var diff = Math.abs(Date.parse(h.t) - tMs);
        if (diff < bestDiff) { bestDiff = diff; nearest = h; projected = false; }
      });
      // The dashed projection line has its own points (PSI only, no PM2.5) --
      // without checking these too, tapping anywhere along it just kept
      // showing the nearest *actual* reading, which barely moves.
      (payload.projection || []).forEach(function (p) {
        var diff = Math.abs(Date.parse(p.t) - tMs);
        if (diff < bestDiff) { bestDiff = diff; nearest = p; projected = true; }
      });
      if (nearest) rows.push({ region: region, row: nearest, projected: projected });
    });
    if (!rows.length) return;
    showTooltip(evt, rows);
  }

  function showTooltip(evt, rows) {
    els.tooltip.innerHTML = "";
    var timeRow = document.createElement("div");
    timeRow.className = "row";
    var k0 = document.createElement("span"); k0.className = "k"; k0.textContent = "Time";
    var tMs0 = Date.parse(rows[0].row.t);
    // Include the date, not just weekday+time -- with up to 60 days of
    // history, "Wed 21:00" alone doesn't say *which* Wednesday.
    var v0 = document.createElement("span"); v0.className = "v"; v0.textContent = fmtAxisDate(tMs0) + " " + fmtSGT(tMs0, { weekday: undefined });
    timeRow.appendChild(k0); timeRow.appendChild(v0);
    els.tooltip.appendChild(timeRow);

    rows.forEach(function (r) {
      var row = document.createElement("div");
      row.className = "row";
      var k = document.createElement("span");
      k.className = "k";
      k.style.color = state.data.colors[r.region];
      k.textContent = capitalize(r.region) + (r.projected ? " (proj.)" : "");
      var v = document.createElement("span");
      v.className = "v";
      var psi = r.row.psi === null || r.row.psi === undefined ? "–" : Math.round(r.row.psi);
      // Projection points only carry a PSI value (see aq_lib.compute_payload) --
      // there's no projected 1-hr PM2.5 reading to show alongside it.
      v.textContent = r.projected ? ("PSI ~" + psi) : ("PSI " + psi + " / PM " + (r.row.pm25_1h === null ? "–" : r.row.pm25_1h.toFixed(1)));
      row.appendChild(k); row.appendChild(v);
      els.tooltip.appendChild(row);
    });

    els.tooltip.hidden = false;
    var left = evt.clientX + 14;
    if (left + 220 > window.innerWidth) left = evt.clientX - 220 - 14;
    els.tooltip.style.left = left + "px";
    els.tooltip.style.top = (evt.clientY + 14) + "px";
  }

  // One row per region, one column per threshold -- a scannable "is this
  // region on track to cross X within 24h, and when" view. The "needed
  // flat PM2.5" value (see aq_lib.time_to_threshold) is the SAME for every
  // region at a given threshold (the flat-hold projection fully replaces
  // the 24h window by hour 24, so the starting baseline drops out of the
  // math) -- what genuinely varies per region is whether today's actual
  // latest reading already puts it on track, and if so, how soon. That's
  // the "reachable"/"hours"/"eta" fields this reads, not needed_flat_pm25.
  function buildStatusTable(data) {
    var colors = data.colors;
    els.statusTableBody.innerHTML = "";
    Object.keys(data.regions).forEach(function (region) {
      var payload = data.regions[region];
      var last = payload.history.length ? payload.history[payload.history.length - 1] : null;
      var tr = document.createElement("tr");

      var regionCell = document.createElement("td");
      regionCell.textContent = capitalize(region);
      regionCell.style.color = colors[region];
      regionCell.style.fontWeight = "600";
      tr.appendChild(regionCell);

      var currentPsi = last && last.psi !== null && last.psi !== undefined ? last.psi : null;
      appendCell(tr, currentPsi !== null ? Math.round(currentPsi) : "–");

      THRESHOLDS.forEach(function (target) {
        // Already past this threshold -- "time until it crosses" doesn't
        // apply, so don't show a dash (which reads as "not on track") or
        // run it through the reachable/hours math at all.
        if (currentPsi !== null && currentPsi >= target) {
          appendCell(tr, "N/A", "status-none");
          return;
        }
        var th = null;
        for (var i = 0; i < payload.thresholds.length; i++) {
          if (payload.thresholds[i].value === target) { th = payload.thresholds[i]; break; }
        }
        if (th && th.reachable) {
          appendCell(tr, th.hours.toFixed(1) + "h (" + fmtSGT(Date.parse(th.eta)) + ")", "status-ok");
        } else {
          appendCell(tr, "–", "status-none");
        }
      });

      els.statusTableBody.appendChild(tr);
    });
  }

  function buildTable(data) {
    var rows = [];
    Object.keys(data.regions).forEach(function (region) {
      data.regions[region].history.forEach(function (h) {
        rows.push({ t: Date.parse(h.t), region: region, row: h });
      });
    });
    rows.sort(function (a, b) { return b.t - a.t; });
    els.tableBody.innerHTML = "";
    rows.forEach(function (r) {
      var tr = document.createElement("tr");
      appendCell(tr, fmtSGT(r.t, { year: "numeric", month: "short", day: "2-digit" }));
      appendCell(tr, capitalize(r.region));
      appendCell(tr, r.row.psi === null ? "–" : Math.round(r.row.psi));
      appendCell(tr, r.row.pm25_1h === null ? "–" : r.row.pm25_1h.toFixed(1));
      appendCell(tr, r.row.pm25_24h === null ? "–" : r.row.pm25_24h.toFixed(1));
      appendCell(tr, r.row.pm25_24h_source || "–");
      els.tableBody.appendChild(tr);
    });
  }

  // ---------------------------------------------------------------------
  // Past-episodes tab -- fetches docs/episodes/data.json lazily, the
  // first time this tab is opened (written by a separate, independently
  // scheduled pipeline -- see build_episodes_page.py).
  // ---------------------------------------------------------------------
  var estate = {
    data: null,
    episode: null,      // the currently-selected episode object
    regionFilter: "all", // "all" or a region name -- which episodes the picker lists
    fullDomain: null,
    viewDomain: null,
    pm25YDomain: null,
    psiYDomain: null,
    panels: [],
    width: 860,
    pinned: false,
    initialized: false, // true once the first fetch of episodes/data.json has been kicked off
  };

  function epiMeasureWidth() {
    var card = document.getElementById("chart-card-epi");
    if (!card) return;
    estate.width = Math.max(280, card.clientWidth - 24);
  }

  // Region filter buttons -- built once per fetch from whichever regions
  // actually have episodes (not hardcoded, so a region with zero episodes
  // in the search window doesn't offer an always-empty filter).
  function epiBuildRegionFilter(episodes) {
    var regions = [];
    episodes.forEach(function (ep) {
      if (regions.indexOf(ep.region) === -1) regions.push(ep.region);
    });
    // Fixed display order (matches the live dashboard's legend), not
    // first-seen order.
    var order = ["north", "south", "east", "west", "central"];
    regions.sort(function (a, b) { return order.indexOf(a) - order.indexOf(b); });

    els.regionFilterEpi.innerHTML = "";
    var allBtn = document.createElement("button");
    allBtn.type = "button";
    allBtn.textContent = "All regions";
    allBtn.dataset.region = "all";
    els.regionFilterEpi.appendChild(allBtn);
    regions.forEach(function (region) {
      var btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = capitalize(region);
      btn.dataset.region = region;
      els.regionFilterEpi.appendChild(btn);
    });
    epiUpdateRegionFilterButtons();

    els.regionFilterEpi.addEventListener("click", function (evt) {
      var btn = evt.target.closest("button");
      if (!btn) return;
      estate.regionFilter = btn.dataset.region;
      epiUpdateRegionFilterButtons();
      epiApplyFilter(true);
    });
  }

  function epiUpdateRegionFilterButtons() {
    var buttons = els.regionFilterEpi.querySelectorAll("button");
    for (var i = 0; i < buttons.length; i++) {
      buttons[i].classList.toggle("active", buttons[i].dataset.region === estate.regionFilter);
    }
  }

  // Episodes matching the current region filter, oldest-first -- the
  // dropdown reads top-to-bottom as a timeline rather than most-recent-first.
  function epiFilteredSortedEpisodes() {
    var list = estate.data.episodes.filter(function (ep) {
      return estate.regionFilter === "all" || ep.region === estate.regionFilter;
    });
    list.sort(function (a, b) { return Date.parse(a.episode_start) - Date.parse(b.episode_start); });
    return list;
  }

  // Rebuilds the episode picker from the current region filter and
  // (re)selects an episode: the previously-selected one if it's still in
  // the filtered list (preserveSelection), else the most recent one.
  function epiApplyFilter(preserveSelection) {
    var list = epiFilteredSortedEpisodes();
    epiBuildSelect(list);
    if (!list.length) return;
    var keepId = preserveSelection && estate.episode && list.some(function (ep) { return ep.id === estate.episode.id; })
      ? estate.episode.id : list[list.length - 1].id;
    epiSelectEpisode(keepId);
  }

  function epiBuildSelect(episodes) {
    els.selectEpi.innerHTML = "";
    episodes.forEach(function (ep) {
      var opt = document.createElement("option");
      opt.value = ep.id;
      opt.textContent = capitalize(ep.region) + " — " + fmtDateTime(Date.parse(ep.episode_start)) +
        " to " + fmtDateTime(Date.parse(ep.episode_end)) + " (" + ep.duration_hours + "h above PSI " +
        estate.data.threshold + ", peak " + Math.round(ep.peak_psi) + ")";
      els.selectEpi.appendChild(opt);
    });
  }

  function epiSelectEpisode(id) {
    var ep = null;
    for (var i = 0; i < estate.data.episodes.length; i++) {
      if (estate.data.episodes[i].id === id) { ep = estate.data.episodes[i]; break; }
    }
    if (!ep) return;
    els.selectEpi.value = id;
    estate.episode = ep;
    estate.pinned = false;
    els.tooltip.hidden = true;

    var allT = ep.series.map(function (pt) { return Date.parse(pt.t); });
    estate.fullDomain = [Math.min.apply(null, allT), Math.max.apply(null, allT)];
    estate.viewDomain = estate.fullDomain.slice();
    epiComputeYDomains(ep);

    els.metaEpi.innerHTML = "<strong>" + capitalize(ep.region) + "</strong> &middot; episode " +
      fmtDateTime(Date.parse(ep.episode_start)) + " to " +
      fmtDateTime(Date.parse(ep.episode_end)) +
      " &middot; " + ep.duration_hours + "h above PSI " + estate.data.threshold +
      " &middot; peak PSI " + Math.round(ep.peak_psi) + " at " + fmtDateTime(Date.parse(ep.peak_time)) +
      " &middot; chart padded " + estate.data.buffer_hours + "h before/after";

    epiBuildTable(ep);
    epiRenderAll();
  }

  function epiComputeYDomains(ep) {
    var pm25Vals = [0], psiVals = [0, estate.data.threshold];
    ep.series.forEach(function (pt) {
      if (pt.pm25_1h !== null) pm25Vals.push(pt.pm25_1h);
      if (pt.psi !== null) psiVals.push(pt.psi);
    });
    var pm25Ticks = niceTicks(Math.min.apply(null, pm25Vals), Math.max.apply(null, pm25Vals), 4);
    var psiTicks = niceTicks(Math.min.apply(null, psiVals), Math.max.apply(null, psiVals), 4);
    estate.pm25YDomain = [pm25Ticks[0], pm25Ticks[pm25Ticks.length - 1]];
    estate.psiYDomain = [psiTicks[0], psiTicks[psiTicks.length - 1]];
  }

  function epiBuildPanel(id, isPsi) { return buildPanelGeneric(id, isPsi, estate.panels, epiAttachInteraction); }

  function epiRenderAll() {
    if (!estate.episode) return;
    estate.panels.forEach(epiRenderPanel);
  }

  function epiRenderPanel(panel) {
    var W = estate.width, H = panelHeight(panel.isPsi);
    var innerW = W - MARGIN.left - MARGIN.right;
    var innerH = panelInnerH(panel.isPsi);

    panel.svg.setAttribute("viewBox", "0 0 " + W + " " + H);
    panel.svg.setAttribute("width", W);
    panel.svg.setAttribute("height", H);
    panel.g.setAttribute("transform", "translate(" + MARGIN.left + "," + MARGIN.top + ")");
    panel.clipRect.setAttribute("x", -2);
    panel.clipRect.setAttribute("y", -2);
    panel.clipRect.setAttribute("width", innerW + 4);
    panel.clipRect.setAttribute("height", innerH + 4);

    panel.gridGroup.innerHTML = "";
    panel.plot.innerHTML = "";
    panel.chromeGroup.innerHTML = "";

    var x = scaleLinear(estate.viewDomain, [0, innerW]);
    var yDomain = panel.isPsi ? estate.psiYDomain : estate.pm25YDomain;
    var y = scaleLinear(yDomain, [innerH, 0]);
    panel.x = x; panel.y = y; panel.innerW = innerW; panel.innerH = innerH;

    var yTicks = niceTicks(yDomain[0], yDomain[1], 4);
    yTicks.forEach(function (t) {
      panel.gridGroup.appendChild(svgEl("line", { x1: 0, x2: innerW, y1: y(t), y2: y(t), stroke: "var(--grid)", "stroke-width": 1 }));
      var lbl = svgEl("text", { class: "axis-label", x: -6, y: y(t) + 3, "text-anchor": "end" });
      lbl.textContent = Math.round(t);
      panel.chromeGroup.appendChild(lbl);
    });

    var timeTickInfo = timeTicks(estate.viewDomain, innerW);
    var useDateTicks = timeTickInfo.stepMs >= ONE_DAY_MS;
    timeTickInfo.ticks.forEach(function (t) {
      var xp = x(t);
      panel.gridGroup.appendChild(svgEl("line", { x1: xp, x2: xp, y1: 0, y2: innerH, stroke: "var(--grid)", "stroke-width": 1 }));
      if (panel.isPsi) {
        panel.chromeGroup.appendChild(svgEl("line", { x1: xp, x2: xp, y1: innerH, y2: innerH + 4, stroke: "var(--faint)", "stroke-width": 1 }));
        var lbl = svgEl("text", { class: "axis-label", x: xp, y: innerH + 15, "text-anchor": "middle" });
        lbl.textContent = useDateTicks ? fmtAxisDate(t) : fmtSGT(t);
        panel.chromeGroup.appendChild(lbl);
      }
    });

    var ep = estate.episode;
    var color = estate.data.colors[ep.region] || "#2a78d6";

    // Shade the actual episode (above-threshold) span so the buffer_hours
    // padding on either side reads as context, not part of the episode itself.
    var epStartX = x(Date.parse(ep.episode_start));
    var epEndX = x(Date.parse(ep.episode_end));
    var bandX0 = Math.max(0, Math.min(epStartX, epEndX));
    var bandX1 = Math.min(innerW, Math.max(epStartX, epEndX));
    if (bandX1 > bandX0) {
      panel.plot.appendChild(svgEl("rect", { x: bandX0, y: 0, width: bandX1 - bandX0, height: innerH, fill: "var(--band)" }));
    }

    if (panel.isPsi) {
      var th = estate.data.threshold;
      if (th >= yDomain[0] && th <= yDomain[1]) {
        panel.plot.appendChild(svgEl("line", { x1: 0, x2: innerW, y1: y(th), y2: y(th), stroke: "var(--faint)", "stroke-width": 1 }));
        var thLbl = svgEl("text", { class: "threshold-label", x: innerW - 2, y: y(th) - 3, "text-anchor": "end" });
        thLbl.textContent = "PSI " + th;
        panel.chromeGroup.appendChild(thLbl);
      }
    }

    var field = panel.isPsi ? "psi" : "pm25_1h";
    var series = ep.series.map(function (pt) { return { t: Date.parse(pt.t), psi: pt.psi, pm25_1h: pt.pm25_1h }; });
    var path = svgEl("path", { d: linePath(series, x, y, "t", field), fill: "none", stroke: color, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" });
    panel.plot.appendChild(path);
    if (series.length <= 200) drawMarkers(panel.plot, series, x, y, "t", field, color);

    var crosshair = svgEl("line", { x1: -10, x2: -10, y1: 0, y2: innerH, stroke: "var(--faint)", "stroke-width": 1, visibility: "hidden" });
    panel.chromeGroup.appendChild(crosshair);
    panel.crosshair = crosshair;
  }

  function epiClampViewDomain(domain) {
    var full = estate.fullDomain;
    var span = Math.min(domain[1] - domain[0], full[1] - full[0]);
    span = Math.max(span, MIN_SPAN_MS);
    var lo = domain[0], hi = lo + span;
    if (lo < full[0]) { lo = full[0]; hi = lo + span; }
    if (hi > full[1]) { hi = full[1]; lo = hi - span; }
    return [lo, hi];
  }

  function epiLocalXFromClientX(svg, clientX) {
    var rect = svg.getBoundingClientRect();
    var scale = estate.width / rect.width;
    return (clientX - rect.left) * scale - MARGIN.left;
  }

  function epiZoomAtLocalX(panel, localX, factor) {
    var frac = Math.max(0, Math.min(1, localX / panel.innerW));
    var cursorT = estate.viewDomain[0] + frac * (estate.viewDomain[1] - estate.viewDomain[0]);
    var span = (estate.viewDomain[1] - estate.viewDomain[0]) * factor;
    var lo = cursorT - frac * span, hi = lo + span;
    estate.viewDomain = epiClampViewDomain([lo, hi]);
    epiRenderAll();
  }

  function epiAttachInteraction(panel) {
    var svg = panel.svg;
    var pointers = {};
    var dragState = null;
    var pinchState = null;

    function activeIds() { return Object.keys(pointers); }
    function distanceBetween(idA, idB) {
      var a = pointers[idA], b = pointers[idB];
      return Math.hypot(a.x - b.x, a.y - b.y);
    }
    function midpointX(idA, idB) { return (pointers[idA].x + pointers[idB].x) / 2; }

    svg.addEventListener("pointerdown", function (evt) {
      evt.preventDefault();
      try { svg.setPointerCapture(evt.pointerId); } catch (e) { /* nice-to-have */ }
      pointers[evt.pointerId] = { x: evt.clientX, y: evt.clientY };
      var ids = activeIds();
      if (ids.length === 2) {
        dragState = null;
        pinchState = { ids: ids, lastDist: distanceBetween(ids[0], ids[1]) };
        svg.classList.remove("dragging");
        panel.tapStart = null;
      } else if (ids.length === 1) {
        pinchState = null;
        svg.classList.add("dragging");
        dragState = { startX: evt.clientX, startDomain: estate.viewDomain.slice() };
        panel.tapStart = { x: evt.clientX, y: evt.clientY };
      }
    });

    svg.addEventListener("pointermove", function (evt) {
      if (!(evt.pointerId in pointers)) { epiHandleHover(panel, evt); return; }
      pointers[evt.pointerId] = { x: evt.clientX, y: evt.clientY };
      if (panel.tapStart && Math.hypot(evt.clientX - panel.tapStart.x, evt.clientY - panel.tapStart.y) > TAP_MAX_MOVE_PX) {
        panel.tapStart = null;
      }
      if (pinchState) {
        evt.preventDefault();
        var ids = pinchState.ids;
        if (!(ids[0] in pointers) || !(ids[1] in pointers)) return;
        var dist = distanceBetween(ids[0], ids[1]);
        if (pinchState.lastDist > 0 && dist > 0) {
          epiZoomAtLocalX(panel, epiLocalXFromClientX(svg, midpointX(ids[0], ids[1])), pinchState.lastDist / dist);
        }
        pinchState.lastDist = dist;
        return;
      }
      if (dragState) {
        evt.preventDefault();
        var scale = estate.width / svg.getBoundingClientRect().width;
        var pxPerMs = panel.innerW / (dragState.startDomain[1] - dragState.startDomain[0]);
        var dxPx = (evt.clientX - dragState.startX) * scale;
        var dtMs = dxPx / pxPerMs;
        estate.viewDomain = epiClampViewDomain([dragState.startDomain[0] - dtMs, dragState.startDomain[1] - dtMs]);
        epiRenderAll();
        return;
      }
      epiHandleHover(panel, evt);
    });

    function endPointer(evt) {
      try { svg.releasePointerCapture(evt.pointerId); } catch (e) { /* already released */ }
      delete pointers[evt.pointerId];
      var ids = activeIds();
      var wasTap = evt.type === "pointerup" && !pinchState && panel.tapStart && ids.length === 0;
      if (pinchState) {
        if (ids.length < 2) {
          pinchState = null;
          if (ids.length === 1) {
            dragState = { startX: pointers[ids[0]].x, startDomain: estate.viewDomain.slice() };
            svg.classList.add("dragging");
          } else {
            svg.classList.remove("dragging");
          }
        }
      } else if (dragState && ids.length === 0) {
        dragState = null;
        svg.classList.remove("dragging");
      }
      if (wasTap) {
        panel.tapStart = null;
        epiSelectPoint(panel, evt);
      }
    }
    svg.addEventListener("pointerup", endPointer);
    svg.addEventListener("pointercancel", endPointer);
    svg.addEventListener("pointerleave", function () {
      if (estate.pinned) return;
      estate.panels.forEach(function (p) { if (p.crosshair) p.crosshair.setAttribute("visibility", "hidden"); });
      els.tooltip.hidden = true;
    });

    svg.addEventListener("wheel", function (evt) {
      evt.preventDefault();
      var factor = evt.deltaY > 0 ? 1.15 : 1 / 1.15;
      epiZoomAtLocalX(panel, epiLocalXFromClientX(svg, evt.clientX), factor);
    }, { passive: false });
  }

  function epiHandleHover(panel, evt) {
    if (estate.pinned) return;
    epiShowReadingsAt(epiTMsFromClientX(panel, evt.clientX), evt);
  }

  function epiSelectPoint(panel, evt) {
    estate.pinned = true;
    epiShowReadingsAt(epiTMsFromClientX(panel, evt.clientX), evt);
  }

  function epiTMsFromClientX(panel, clientX) {
    var localX = epiLocalXFromClientX(panel.svg, clientX);
    var clampedX = Math.max(0, Math.min(panel.innerW, localX));
    return estate.viewDomain[0] + (clampedX / panel.innerW) * (estate.viewDomain[1] - estate.viewDomain[0]);
  }

  function epiShowReadingsAt(tMs, evt) {
    estate.panels.forEach(function (p) {
      var cx = p.x ? p.x(tMs) : -10;
      if (p.crosshair) {
        p.crosshair.setAttribute("x1", cx);
        p.crosshair.setAttribute("x2", cx);
        p.crosshair.setAttribute("visibility", "visible");
      }
    });

    var series = estate.episode.series;
    var nearest = null, bestDiff = Infinity;
    for (var i = 0; i < series.length; i++) {
      var diff = Math.abs(Date.parse(series[i].t) - tMs);
      if (diff < bestDiff) { bestDiff = diff; nearest = series[i]; }
    }
    if (!nearest) return;
    epiShowTooltip(evt, nearest);
  }

  function epiShowTooltip(evt, row) {
    els.tooltip.innerHTML = "";
    var tMs = Date.parse(row.t);
    var timeRow = document.createElement("div");
    timeRow.className = "row";
    var k0 = document.createElement("span"); k0.className = "k"; k0.textContent = "Time";
    var v0 = document.createElement("span"); v0.className = "v"; v0.textContent = fmtDateTime(tMs);
    timeRow.appendChild(k0); timeRow.appendChild(v0);
    els.tooltip.appendChild(timeRow);

    var row2 = document.createElement("div");
    row2.className = "row";
    var k = document.createElement("span"); k.className = "k"; k.textContent = capitalize(estate.episode.region);
    var v = document.createElement("span"); v.className = "v";
    var psi = row.psi === null ? "–" : Math.round(row.psi);
    var pm = row.pm25_1h === null ? "–" : row.pm25_1h.toFixed(1);
    v.textContent = "PSI " + psi + " / PM " + pm;
    row2.appendChild(k); row2.appendChild(v);
    els.tooltip.appendChild(row2);

    els.tooltip.hidden = false;
    var left = evt.clientX + 14;
    if (left + 220 > window.innerWidth) left = evt.clientX - 220 - 14;
    els.tooltip.style.left = left + "px";
    els.tooltip.style.top = (evt.clientY + 14) + "px";
  }

  function epiBuildTable(ep) {
    var rows = ep.series.slice().sort(function (a, b) { return Date.parse(b.t) - Date.parse(a.t); });
    els.tableBodyEpi.innerHTML = "";
    rows.forEach(function (r) {
      var tr = document.createElement("tr");
      appendCell(tr, fmtDateTime(Date.parse(r.t)));
      appendCell(tr, r.psi === null ? "–" : Math.round(r.psi));
      appendCell(tr, r.pm25_1h === null ? "–" : r.pm25_1h.toFixed(1));
      els.tableBodyEpi.appendChild(tr);
    });
  }

  function epiInit() {
    fetch("episodes/data.json", { cache: "no-store" })
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (data) {
        estate.data = data;
        els.subtitleEpi.textContent = "Searched " + fmtAxisDate(Date.parse(data.search_start)) + " to " +
          fmtAxisDate(Date.parse(data.search_end)) + " for PSI > " + data.threshold +
          " -- " + data.episodes.length + " episode(s) found";

        if (!data.episodes.length) {
          els.regionFilterEpi.hidden = true;
          document.querySelector("#tab-panel-episodes .picker-row").hidden = true;
          document.querySelector("#tab-panel-episodes .toolbar").hidden = true;
          var p = document.createElement("p");
          p.className = "empty-state";
          p.textContent = "No episodes found -- every region stayed at or below PSI " + data.threshold + " for the whole search window.";
          document.getElementById("chart-card-epi").replaceWith(p);
          document.querySelector("#tab-panel-episodes .table-section").hidden = true;
          return;
        }

        epiBuildRegionFilter(data.episodes);
        epiMeasureWidth();
        epiBuildPanel("chart-pm25-epi", false);
        epiBuildPanel("chart-psi-epi", true);
        epiApplyFilter(false);
      })
      .catch(function (err) {
        els.subtitleEpi.textContent = "Failed to load episode data";
        var p = document.createElement("p");
        p.className = "empty-state";
        p.textContent = "Could not load episode data (" + err.message + ").";
        var card = document.getElementById("chart-card-epi");
        if (card) card.replaceWith(p);
      });
  }

  // ---------------------------------------------------------------------
  // 2015 Haze tab -- fetches docs/haze2015/data.json lazily, the first
  // time this tab is opened (written by a separate, manually-triggered
  // one-off pipeline -- see fetch_haze2015_data.py/build_haze2015_page.py).
  // Structurally like the live dashboard tab (multi-region overlay on two
  // panels) but with no projection and no threshold reference lines: this
  // is purely historical, so there's nothing to forecast.
  // ---------------------------------------------------------------------
  var h15 = {
    data: null,
    fullDomain: null,
    viewDomain: null,
    pm25YDomain: null,
    psiYDomain: null,
    panels: [],
    width: 860,
    pinned: false,
    initialized: false,
  };

  function h15MeasureWidth() {
    var card = document.getElementById("chart-card-h15");
    if (!card) return;
    h15.width = Math.max(280, card.clientWidth - 24);
  }

  function h15BuildLegend(colors) {
    els.legendH15.innerHTML = "";
    Object.keys(colors).forEach(function (region) {
      var span = document.createElement("span");
      span.className = "key";
      var sw = document.createElement("span");
      sw.className = "swatch";
      sw.style.background = colors[region];
      var label = document.createElement("span");
      label.textContent = capitalize(region);
      span.appendChild(sw);
      span.appendChild(label);
      els.legendH15.appendChild(span);
    });
  }

  function h15ComputeYDomains() {
    var pm25Vals = [0], psiVals = [0];
    Object.keys(h15.data.regions).forEach(function (region) {
      h15.data.regions[region].history.forEach(function (h) {
        if (h.pm25_1h !== null) pm25Vals.push(h.pm25_1h);
        if (h.psi !== null) psiVals.push(h.psi);
      });
    });
    var pm25Ticks = niceTicks(Math.min.apply(null, pm25Vals), Math.max.apply(null, pm25Vals), 4);
    var psiTicks = niceTicks(Math.min.apply(null, psiVals), Math.max.apply(null, psiVals), 4);
    h15.pm25YDomain = [pm25Ticks[0], pm25Ticks[pm25Ticks.length - 1]];
    h15.psiYDomain = [psiTicks[0], psiTicks[psiTicks.length - 1]];
  }

  function h15BuildPanel(id, isPsi) { return buildPanelGeneric(id, isPsi, h15.panels, h15AttachInteraction); }

  function h15RenderAll() {
    if (!h15.data) return;
    h15.panels.forEach(h15RenderPanel);
  }

  function h15RenderPanel(panel) {
    var W = h15.width, H = panelHeight(panel.isPsi);
    var innerW = W - MARGIN.left - MARGIN.right;
    var innerH = panelInnerH(panel.isPsi);

    panel.svg.setAttribute("viewBox", "0 0 " + W + " " + H);
    panel.svg.setAttribute("width", W);
    panel.svg.setAttribute("height", H);
    panel.g.setAttribute("transform", "translate(" + MARGIN.left + "," + MARGIN.top + ")");
    panel.clipRect.setAttribute("x", -2);
    panel.clipRect.setAttribute("y", -2);
    panel.clipRect.setAttribute("width", innerW + 4);
    panel.clipRect.setAttribute("height", innerH + 4);

    panel.gridGroup.innerHTML = "";
    panel.plot.innerHTML = "";
    panel.chromeGroup.innerHTML = "";

    var x = scaleLinear(h15.viewDomain, [0, innerW]);
    var yDomain = panel.isPsi ? h15.psiYDomain : h15.pm25YDomain;
    var y = scaleLinear(yDomain, [innerH, 0]);
    panel.x = x; panel.y = y; panel.innerW = innerW; panel.innerH = innerH;

    var yTicks = niceTicks(yDomain[0], yDomain[1], 4);
    yTicks.forEach(function (t) {
      panel.gridGroup.appendChild(svgEl("line", { x1: 0, x2: innerW, y1: y(t), y2: y(t), stroke: "var(--grid)", "stroke-width": 1 }));
      var lbl = svgEl("text", { class: "axis-label", x: -6, y: y(t) + 3, "text-anchor": "end" });
      lbl.textContent = Math.round(t);
      panel.chromeGroup.appendChild(lbl);
    });

    var timeTickInfo = timeTicks(h15.viewDomain, innerW);
    var useDateTicks = timeTickInfo.stepMs >= ONE_DAY_MS;
    timeTickInfo.ticks.forEach(function (t) {
      var xp = x(t);
      panel.gridGroup.appendChild(svgEl("line", { x1: xp, x2: xp, y1: 0, y2: innerH, stroke: "var(--grid)", "stroke-width": 1 }));
      if (panel.isPsi) {
        panel.chromeGroup.appendChild(svgEl("line", { x1: xp, x2: xp, y1: innerH, y2: innerH + 4, stroke: "var(--faint)", "stroke-width": 1 }));
        var lbl = svgEl("text", { class: "axis-label", x: xp, y: innerH + 15, "text-anchor": "middle" });
        lbl.textContent = useDateTicks ? fmtAxisDate(t) : fmtSGT(t);
        panel.chromeGroup.appendChild(lbl);
      }
    });

    var colors = h15.data.colors;
    var regions = Object.keys(h15.data.regions);

    regions.forEach(function (region) {
      var payload = h15.data.regions[region];
      var color = colors[region];
      var hist = payload.history.map(function (h) { return { t: Date.parse(h.t), psi: h.psi, pm25_1h: h.pm25_1h }; });
      var field = panel.isPsi ? "psi" : "pm25_1h";
      var path = svgEl("path", {
        d: linePath(hist, x, y, "t", field), fill: "none", stroke: color,
        "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round"
      });
      panel.plot.appendChild(path);

      if (h15CountInView(hist, "t") <= MAX_MARKER_POINTS) {
        drawMarkers(panel.plot, hist, x, y, "t", field, color, 1);
      }
    });

    var crosshair = svgEl("line", { x1: -10, x2: -10, y1: 0, y2: innerH, stroke: "var(--faint)", "stroke-width": 1, visibility: "hidden" });
    panel.chromeGroup.appendChild(crosshair);
    panel.crosshair = crosshair;
  }

  function h15CountInView(points, xField) {
    var lo = h15.viewDomain[0], hi = h15.viewDomain[1], n = 0;
    for (var i = 0; i < points.length; i++) {
      var t = points[i][xField];
      if (t >= lo && t <= hi) n++;
    }
    return n;
  }

  function h15ClampViewDomain(domain) {
    var full = h15.fullDomain;
    var span = Math.min(domain[1] - domain[0], full[1] - full[0]);
    span = Math.max(span, MIN_SPAN_MS);
    var lo = domain[0], hi = lo + span;
    if (lo < full[0]) { lo = full[0]; hi = lo + span; }
    if (hi > full[1]) { hi = full[1]; lo = hi - span; }
    return [lo, hi];
  }

  function h15LocalXFromClientX(svg, clientX) {
    var rect = svg.getBoundingClientRect();
    var scale = h15.width / rect.width;
    return (clientX - rect.left) * scale - MARGIN.left;
  }

  function h15ZoomAtLocalX(panel, localX, factor) {
    var frac = Math.max(0, Math.min(1, localX / panel.innerW));
    var cursorT = h15.viewDomain[0] + frac * (h15.viewDomain[1] - h15.viewDomain[0]);
    var span = (h15.viewDomain[1] - h15.viewDomain[0]) * factor;
    var lo = cursorT - frac * span, hi = lo + span;
    h15.viewDomain = h15ClampViewDomain([lo, hi]);
    h15RenderAll();
  }

  function h15AttachInteraction(panel) {
    var svg = panel.svg;
    var pointers = {};
    var dragState = null;
    var pinchState = null;

    function activeIds() { return Object.keys(pointers); }
    function distanceBetween(idA, idB) {
      var a = pointers[idA], b = pointers[idB];
      return Math.hypot(a.x - b.x, a.y - b.y);
    }
    function midpointX(idA, idB) { return (pointers[idA].x + pointers[idB].x) / 2; }

    svg.addEventListener("pointerdown", function (evt) {
      evt.preventDefault();
      try { svg.setPointerCapture(evt.pointerId); } catch (e) { /* nice-to-have */ }
      pointers[evt.pointerId] = { x: evt.clientX, y: evt.clientY };
      var ids = activeIds();
      if (ids.length === 2) {
        dragState = null;
        pinchState = { ids: ids, lastDist: distanceBetween(ids[0], ids[1]) };
        svg.classList.remove("dragging");
        panel.tapStart = null;
      } else if (ids.length === 1) {
        pinchState = null;
        svg.classList.add("dragging");
        dragState = { startX: evt.clientX, startDomain: h15.viewDomain.slice() };
        panel.tapStart = { x: evt.clientX, y: evt.clientY };
      }
    });

    svg.addEventListener("pointermove", function (evt) {
      if (!(evt.pointerId in pointers)) { h15HandleHover(panel, evt); return; }
      pointers[evt.pointerId] = { x: evt.clientX, y: evt.clientY };
      if (panel.tapStart && Math.hypot(evt.clientX - panel.tapStart.x, evt.clientY - panel.tapStart.y) > TAP_MAX_MOVE_PX) {
        panel.tapStart = null;
      }
      if (pinchState) {
        evt.preventDefault();
        var ids = pinchState.ids;
        if (!(ids[0] in pointers) || !(ids[1] in pointers)) return;
        var dist = distanceBetween(ids[0], ids[1]);
        if (pinchState.lastDist > 0 && dist > 0) {
          h15ZoomAtLocalX(panel, h15LocalXFromClientX(svg, midpointX(ids[0], ids[1])), pinchState.lastDist / dist);
        }
        pinchState.lastDist = dist;
        return;
      }
      if (dragState) {
        evt.preventDefault();
        var scale = h15.width / svg.getBoundingClientRect().width;
        var pxPerMs = panel.innerW / (dragState.startDomain[1] - dragState.startDomain[0]);
        var dxPx = (evt.clientX - dragState.startX) * scale;
        var dtMs = dxPx / pxPerMs;
        h15.viewDomain = h15ClampViewDomain([dragState.startDomain[0] - dtMs, dragState.startDomain[1] - dtMs]);
        h15RenderAll();
        return;
      }
      h15HandleHover(panel, evt);
    });

    function endPointer(evt) {
      try { svg.releasePointerCapture(evt.pointerId); } catch (e) { /* already released */ }
      delete pointers[evt.pointerId];
      var ids = activeIds();
      var wasTap = evt.type === "pointerup" && !pinchState && panel.tapStart && ids.length === 0;
      if (pinchState) {
        if (ids.length < 2) {
          pinchState = null;
          if (ids.length === 1) {
            dragState = { startX: pointers[ids[0]].x, startDomain: h15.viewDomain.slice() };
            svg.classList.add("dragging");
          } else {
            svg.classList.remove("dragging");
          }
        }
      } else if (dragState && ids.length === 0) {
        dragState = null;
        svg.classList.remove("dragging");
      }
      if (wasTap) {
        panel.tapStart = null;
        h15SelectPoint(panel, evt);
      }
    }
    svg.addEventListener("pointerup", endPointer);
    svg.addEventListener("pointercancel", endPointer);
    svg.addEventListener("pointerleave", function () {
      if (h15.pinned) return;
      h15.panels.forEach(function (p) { if (p.crosshair) p.crosshair.setAttribute("visibility", "hidden"); });
      els.tooltip.hidden = true;
    });

    svg.addEventListener("wheel", function (evt) {
      evt.preventDefault();
      var factor = evt.deltaY > 0 ? 1.15 : 1 / 1.15;
      h15ZoomAtLocalX(panel, h15LocalXFromClientX(svg, evt.clientX), factor);
    }, { passive: false });
  }

  function h15HandleHover(panel, evt) {
    if (h15.pinned) return;
    h15ShowReadingsAt(h15TMsFromClientX(panel, evt.clientX), evt);
  }

  function h15SelectPoint(panel, evt) {
    h15.pinned = true;
    h15ShowReadingsAt(h15TMsFromClientX(panel, evt.clientX), evt);
  }

  function h15TMsFromClientX(panel, clientX) {
    var localX = h15LocalXFromClientX(panel.svg, clientX);
    var clampedX = Math.max(0, Math.min(panel.innerW, localX));
    return h15.viewDomain[0] + (clampedX / panel.innerW) * (h15.viewDomain[1] - h15.viewDomain[0]);
  }

  function h15ShowReadingsAt(tMs, evt) {
    h15.panels.forEach(function (p) {
      var cx = p.x ? p.x(tMs) : -10;
      if (p.crosshair) {
        p.crosshair.setAttribute("x1", cx);
        p.crosshair.setAttribute("x2", cx);
        p.crosshair.setAttribute("visibility", "visible");
      }
    });

    var rows = [];
    var regions = Object.keys(h15.data.regions);
    regions.forEach(function (region) {
      var payload = h15.data.regions[region];
      var nearest = null, bestDiff = Infinity;
      payload.history.forEach(function (h) {
        var diff = Math.abs(Date.parse(h.t) - tMs);
        if (diff < bestDiff) { bestDiff = diff; nearest = h; }
      });
      if (nearest) rows.push({ region: region, row: nearest });
    });
    if (!rows.length) return;
    h15ShowTooltip(evt, rows);
  }

  function h15ShowTooltip(evt, rows) {
    els.tooltip.innerHTML = "";
    var timeRow = document.createElement("div");
    timeRow.className = "row";
    var k0 = document.createElement("span"); k0.className = "k"; k0.textContent = "Time";
    var tMs0 = Date.parse(rows[0].row.t);
    var v0 = document.createElement("span"); v0.className = "v"; v0.textContent = fmtDateTime(tMs0);
    timeRow.appendChild(k0); timeRow.appendChild(v0);
    els.tooltip.appendChild(timeRow);

    rows.forEach(function (r) {
      var row = document.createElement("div");
      row.className = "row";
      var k = document.createElement("span");
      k.className = "k";
      k.style.color = h15.data.colors[r.region];
      k.textContent = capitalize(r.region);
      var v = document.createElement("span");
      v.className = "v";
      var psi = r.row.psi === null || r.row.psi === undefined ? "–" : Math.round(r.row.psi);
      v.textContent = "PSI " + psi + " / PM " + (r.row.pm25_1h === null ? "–" : r.row.pm25_1h.toFixed(1));
      row.appendChild(k); row.appendChild(v);
      els.tooltip.appendChild(row);
    });

    els.tooltip.hidden = false;
    var left = evt.clientX + 14;
    if (left + 220 > window.innerWidth) left = evt.clientX - 220 - 14;
    els.tooltip.style.left = left + "px";
    els.tooltip.style.top = (evt.clientY + 14) + "px";
  }

  function h15BuildTable(data) {
    var rows = [];
    Object.keys(data.regions).forEach(function (region) {
      data.regions[region].history.forEach(function (h) {
        rows.push({ t: Date.parse(h.t), region: region, row: h });
      });
    });
    rows.sort(function (a, b) { return b.t - a.t; });
    els.tableBodyH15.innerHTML = "";
    rows.forEach(function (r) {
      var tr = document.createElement("tr");
      appendCell(tr, fmtDateTime(r.t));
      appendCell(tr, capitalize(r.region));
      appendCell(tr, r.row.psi === null ? "–" : Math.round(r.row.psi));
      appendCell(tr, r.row.pm25_1h === null ? "–" : r.row.pm25_1h.toFixed(1));
      els.tableBodyH15.appendChild(tr);
    });
  }

  function h15Init() {
    fetch("haze2015/data.json", { cache: "no-store" })
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (data) {
        h15.data = data;
        var allT = [];
        Object.keys(data.regions).forEach(function (region) {
          data.regions[region].history.forEach(function (h) { allT.push(Date.parse(h.t)); });
        });
        if (!allT.length) throw new Error("no data points in haze2015/data.json");
        h15.fullDomain = [Math.min.apply(null, allT), Math.max.apply(null, allT)];
        h15.viewDomain = h15.fullDomain.slice();
        h15ComputeYDomains();

        els.subtitleH15.textContent = "Historical NEA data, " + fmtAxisDate(h15.fullDomain[0]) + " to " + fmtAxisDate(h15.fullDomain[1]) + " SGT";

        h15BuildLegend(data.colors);
        h15BuildTable(data);
        h15MeasureWidth();
        h15BuildPanel("chart-pm25-h15", false);
        h15BuildPanel("chart-psi-h15", true);
        h15RenderAll();
      })
      .catch(function (err) {
        els.subtitleH15.textContent = "Failed to load 2015 haze data";
        var p = document.createElement("p");
        p.className = "empty-state";
        p.textContent = "Could not load 2015 haze data (" + err.message + ").";
        var card = document.getElementById("chart-card-h15");
        if (card) card.replaceWith(p);
      });
  }

  // ---------------------------------------------------------------------
  // What-if Projection tab -- lets the user enter their own 24-hr PSI and
  // 1-hr PM2.5 ranges (prefilled from the Live dashboard's latest readings
  // the first time this tab is opened) and runs the same flat-hold
  // projection model as the Live dashboard tab, but out to 72h (3 days)
  // instead of 24h, and entirely client-side from the entered numbers --
  // there's no new data file/workflow behind this tab.
  //
  // The model is linear and non-decreasing in both the baseline (PSI) and
  // the held-flat latest reading (PM2.5), so the pointwise low/high band is
  // exactly the model run once at (psiLow, pmLow) and once at (psiHigh,
  // pmHigh) -- no need to enumerate all four corner combinations.
  // ---------------------------------------------------------------------
  var WHATIF_HOURS = 72; // nominal 3 days -- see wiEndHours() for why the actual span usually runs a bit longer

  var wi = {
    nowMs: null,        // anchor time for the projection (the Live dashboard's latest-reading timestamp)
    hours: null,         // actual projection length in hours (>= WHATIF_HOURS, rounded up to end-of-day SGT)
    lowSeries: null,     // [{t, avgPm25, psi, latest1h}]
    highSeries: null,
    injections: [],      // [{idx, which}] -- points where the user has injected a new value, for the chart markers
    fullDomain: null,
    viewDomain: null,
    pm25YDomain: null,
    psiYDomain: null,
    panels: [],
    width: 860,
    pinned: false,
    initialized: false,  // true once this tab's first activation has kicked off
  };
  var onLiveDataReady = []; // callbacks queued if this tab opens before the Live dashboard's fetch resolves

  // "Now + 72h" usually lands mid-day, which would cut the chart off
  // partway through its final day -- extend that end point forward to
  // 23:00 SGT of whichever day it falls on, so the last day is always
  // shown in full (never backward, so the window is still at least 72h).
  function wiEndHours(nowMs) {
    var roughEndMs = nowMs + WHATIF_HOURS * 3600 * 1000;
    var localEnd = roughEndMs + SG_OFFSET_MS;
    var localDayStart = Math.floor(localEnd / ONE_DAY_MS) * ONE_DAY_MS;
    var dayEndMs = (localDayStart + 23 * 3600 * 1000) - SG_OFFSET_MS;
    var endMs = Math.max(roughEndMs, dayEndMs);
    return Math.round((endMs - nowMs) / 3600000);
  }

  function wiMeasureWidth() {
    var card = document.getElementById("chart-card-whatif");
    if (!card) return;
    wi.width = Math.max(280, card.clientWidth - 24);
  }

  function wiPopulateDefaults() {
    var psiVals = [], pmVals = [];
    Object.keys(state.data.regions).forEach(function (region) {
      var hist = state.data.regions[region].history;
      var last = hist.length ? hist[hist.length - 1] : null;
      if (!last) return;
      if (last.psi !== null && last.psi !== undefined) psiVals.push(last.psi);
      if (last.pm25_1h !== null && last.pm25_1h !== undefined) pmVals.push(last.pm25_1h);
    });
    if (psiVals.length) {
      els.wiPsiLow.value = Math.round(Math.min.apply(null, psiVals));
      els.wiPsiHigh.value = Math.round(Math.max.apply(null, psiVals));
    }
    if (pmVals.length) {
      els.wiPmLow.value = Math.min.apply(null, pmVals).toFixed(1);
      els.wiPmHigh.value = Math.max.apply(null, pmVals).toFixed(1);
    }
    var asOfMs = Math.max.apply(null, Object.keys(state.data.regions).map(function (r) {
      return Date.parse(state.data.regions[r].as_of);
    }));
    wi.nowMs = asOfMs;
    els.subtitleWhatif.textContent = "Default range is today's min–max across all regions, as of " +
      fmtDateTime(asOfMs) + " SGT — edit and recalculate as you like.";
  }

  function wiCalculate() {
    var psiLow = parseFloat(els.wiPsiLow.value);
    var psiHigh = parseFloat(els.wiPsiHigh.value);
    var pmLow = parseFloat(els.wiPmLow.value);
    var pmHigh = parseFloat(els.wiPmHigh.value);

    var errs = [];
    [["24-hr PSI low", psiLow], ["24-hr PSI high", psiHigh], ["1-hr PM2.5 low", pmLow], ["1-hr PM2.5 high", pmHigh]].forEach(function (pair) {
      if (!isFinite(pair[1]) || pair[1] < 0) errs.push(pair[0] + " must be a non-negative number");
    });
    if (!errs.length && psiLow > psiHigh) errs.push("24-hr PSI low must be ≤ high");
    if (!errs.length && pmLow > pmHigh) errs.push("1-hr PM2.5 low must be ≤ high");

    if (errs.length) {
      els.whatifError.textContent = errs.join("; ");
      els.whatifError.hidden = false;
      return;
    }
    els.whatifError.hidden = true;

    var baselineLow = psiToPm25(psiLow);
    var baselineHigh = psiToPm25(psiHigh);

    wi.hours = wiEndHours(wi.nowMs);
    var lowSeries = [], highSeries = [];
    for (var h = 0; h <= wi.hours; h++) {
      var tMs = wi.nowMs + h * 3600 * 1000;
      var avgLow = h <= 24 ? projectedAvgPm25(baselineLow, pmLow, h) : pmLow;
      var avgHigh = h <= 24 ? projectedAvgPm25(baselineHigh, pmHigh, h) : pmHigh;
      var tIso = new Date(tMs).toISOString();
      // avgPm25 (the 24-hr-average-equivalent at this hour) is kept, not
      // just the derived PSI, so a later wiInjectAt() has the right
      // starting baseline to re-anchor the flat-hold formula from -- the
      // same role the live dashboard's own "baseline" plays at hour 0.
      // latest1h is the actual 1-hr reading the model assumes holds flat --
      // constant at pmLow/pmHigh until an injection changes it (a step,
      // not a ramp: unlike the 24-hr average, there's no "window" to fill).
      lowSeries.push({ t: tIso, avgPm25: avgLow, psi: pm25ToPsi(avgLow), latest1h: pmLow });
      highSeries.push({ t: tIso, avgPm25: avgHigh, psi: pm25ToPsi(avgHigh), latest1h: pmHigh });
    }
    wi.lowSeries = lowSeries;
    wi.highSeries = highSeries;
    wi.injections = []; // [{idx, which}] -- cleared on every fresh Calculate
    wi.fullDomain = [wi.nowMs, wi.nowMs + wi.hours * 3600 * 1000];
    wi.viewDomain = wi.fullDomain.slice();
    wi.pinned = false;
    els.tooltip.hidden = true;
    wiComputeYDomain();
    wiBuildTable();

    if (!wi.panels.length) {
      wiMeasureWidth();
      wiBuildPanel("chart-pm25-whatif", false);
      wiBuildPanel("chart-psi-whatif", true);
    }
    wiRenderAll();
  }

  function wiComputeYDomain() {
    var psiVals = [0].concat(THRESHOLDS), pm25Vals = [0];
    wi.lowSeries.forEach(function (p) { psiVals.push(p.psi); pm25Vals.push(p.latest1h); });
    wi.highSeries.forEach(function (p) { psiVals.push(p.psi); pm25Vals.push(p.latest1h); });
    var psiTicks = niceTicks(Math.min.apply(null, psiVals), Math.max.apply(null, psiVals), 4);
    var pm25Ticks = niceTicks(Math.min.apply(null, pm25Vals), Math.max.apply(null, pm25Vals), 4);
    wi.psiYDomain = [psiTicks[0], psiTicks[psiTicks.length - 1]];
    wi.pm25YDomain = [pm25Ticks[0], pm25Ticks[pm25Ticks.length - 1]];
  }

  // Injects a new "hold flat from here" 1-hr PM2.5 value at hour `idx` on
  // the low or high line. Two different things change, on two different
  // timelines:
  //   - latest1h is the actual 1-hr reading -- it steps to the new value
  //     immediately at idx and stays there (no "window" to fill, so no ramp).
  //   - avgPm25 (and the psi derived from it) is the 24-hr rolling average,
  //     which re-anchors the same flat-hold formula wiCalculate() uses,
  //     starting from this hour's own avgPm25 as the new baseline instead
  //     of hour 0's -- it only fully catches up to the new value 24h later.
  function wiInjectAt(which, idx) {
    var series = which === "low" ? wi.lowSeries : wi.highSeries;
    var point = series[idx];
    var input = window.prompt(
      "New 1-hr PM2.5 (µg/m³) to hold flat from " + fmtDateTime(Date.parse(point.t)) + " onward:",
      point.latest1h.toFixed(1)
    );
    if (input === null) return; // cancelled
    var newLatest = parseFloat(input);
    if (!isFinite(newLatest) || newLatest < 0) {
      window.alert("Please enter a non-negative number.");
      return;
    }

    var baseline = point.avgPm25;
    for (var i = idx; i < series.length; i++) {
      var dt = i - idx;
      var avg = dt === 0 ? baseline : (dt <= 24 ? projectedAvgPm25(baseline, newLatest, dt) : newLatest);
      series[i].avgPm25 = avg;
      series[i].psi = pm25ToPsi(avg);
      series[i].latest1h = newLatest;
    }
    wi.injections.push({ idx: idx, which: which });

    wi.pinned = false;
    els.tooltip.hidden = true;
    wiComputeYDomain();
    wiBuildTable();
    wiRenderAll();
  }

  function wiBuildPanel(id, isPsi) { return buildPanelGeneric(id, isPsi, wi.panels, wiAttachInteraction); }

  function wiRenderAll() {
    if (!wi.lowSeries) return;
    wi.panels.forEach(wiRenderPanel);
  }

  function wiRenderPanel(panel) {
    var W = wi.width, H = panelHeight(panel.isPsi);
    var innerW = W - MARGIN.left - MARGIN.right;
    var innerH = panelInnerH(panel.isPsi);

    panel.svg.setAttribute("viewBox", "0 0 " + W + " " + H);
    panel.svg.setAttribute("width", W);
    panel.svg.setAttribute("height", H);
    panel.g.setAttribute("transform", "translate(" + MARGIN.left + "," + MARGIN.top + ")");
    panel.clipRect.setAttribute("x", -2);
    panel.clipRect.setAttribute("y", -2);
    panel.clipRect.setAttribute("width", innerW + 4);
    panel.clipRect.setAttribute("height", innerH + 4);

    panel.gridGroup.innerHTML = "";
    panel.plot.innerHTML = "";
    panel.chromeGroup.innerHTML = "";

    var field = panel.isPsi ? "psi" : "latest1h";
    var yDomain = panel.isPsi ? wi.psiYDomain : wi.pm25YDomain;
    var x = scaleLinear(wi.viewDomain, [0, innerW]);
    var y = scaleLinear(yDomain, [innerH, 0]);
    panel.x = x; panel.y = y; panel.innerW = innerW; panel.innerH = innerH;

    var yTicks = niceTicks(yDomain[0], yDomain[1], 4);
    yTicks.forEach(function (t) {
      panel.gridGroup.appendChild(svgEl("line", { x1: 0, x2: innerW, y1: y(t), y2: y(t), stroke: "var(--grid)", "stroke-width": 1 }));
      var lbl = svgEl("text", { class: "axis-label", x: -6, y: y(t) + 3, "text-anchor": "end" });
      lbl.textContent = Math.round(t);
      panel.chromeGroup.appendChild(lbl);
    });

    var timeTickInfo = timeTicks(wi.viewDomain, innerW);
    var useDateTicks = timeTickInfo.stepMs >= ONE_DAY_MS;
    timeTickInfo.ticks.forEach(function (t) {
      var xp = x(t);
      panel.gridGroup.appendChild(svgEl("line", { x1: xp, x2: xp, y1: 0, y2: innerH, stroke: "var(--grid)", "stroke-width": 1 }));
      if (panel.isPsi) {
        panel.chromeGroup.appendChild(svgEl("line", { x1: xp, x2: xp, y1: innerH, y2: innerH + 4, stroke: "var(--faint)", "stroke-width": 1 }));
        var lbl = svgEl("text", { class: "axis-label", x: xp, y: innerH + 15, "text-anchor": "middle" });
        lbl.textContent = useDateTicks ? fmtAxisDate(t) : fmtSGT(t);
        panel.chromeGroup.appendChild(lbl);
      }
    });

    if (panel.isPsi) {
      THRESHOLDS.forEach(function (th) {
        if (th < yDomain[0] || th > yDomain[1]) return;
        panel.plot.appendChild(svgEl("line", { x1: 0, x2: innerW, y1: y(th), y2: y(th), stroke: "var(--faint)", "stroke-width": 1 }));
        var lbl = svgEl("text", { class: "threshold-label", x: innerW - 2, y: y(th) - 3, "text-anchor": "end" });
        lbl.textContent = "PSI " + th;
        panel.chromeGroup.appendChild(lbl);
      });
    }

    var lowPts = wi.lowSeries.map(function (p) { return { t: Date.parse(p.t), v: p[field] }; });
    var highPts = wi.highSeries.map(function (p) { return { t: Date.parse(p.t), v: p[field] }; });

    // Shaded band between the low and high scenario -- a closed polygon
    // tracing the low line left-to-right then the high line back right-to-left.
    var bandPts = lowPts.map(function (p) { return x(p.t).toFixed(1) + "," + y(p.v).toFixed(1); })
      .concat(highPts.slice().reverse().map(function (p) { return x(p.t).toFixed(1) + "," + y(p.v).toFixed(1); }));
    panel.plot.appendChild(svgEl("polygon", { points: bandPts.join(" "), fill: "var(--whatif-band)", stroke: "none" }));

    panel.plot.appendChild(svgEl("path", {
      d: linePath(lowPts, x, y, "t", "v"), fill: "none", stroke: "var(--whatif-line)",
      "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round"
    }));
    panel.plot.appendChild(svgEl("path", {
      d: linePath(highPts, x, y, "t", "v"), fill: "none", stroke: "var(--whatif-line)",
      "stroke-width": 2, "stroke-dasharray": "6 4", "stroke-linejoin": "round", "stroke-linecap": "round"
    }));
    if (lowPts.length <= MAX_MARKER_POINTS * 2) {
      drawMarkers(panel.plot, lowPts, x, y, "t", "v", "var(--whatif-line)", 1);
      drawMarkers(panel.plot, highPts, x, y, "t", "v", "var(--whatif-line)", 0.6);
    }

    // Larger ringed marker at each hour the user has injected a new value,
    // so an edited line reads as deliberately reshaped, not just noisy.
    wi.injections.forEach(function (inj) {
      var pts = inj.which === "low" ? lowPts : highPts;
      var p = pts[inj.idx];
      if (!p) return;
      panel.plot.appendChild(svgEl("circle", {
        cx: x(p.t).toFixed(1), cy: y(p.v).toFixed(1), r: 5,
        fill: "var(--surface)", stroke: "var(--whatif-line)", "stroke-width": 2
      }));
    });

    var crosshair = svgEl("line", { x1: -10, x2: -10, y1: 0, y2: innerH, stroke: "var(--faint)", "stroke-width": 1, visibility: "hidden" });
    panel.chromeGroup.appendChild(crosshair);
    panel.crosshair = crosshair;
  }

  function wiClampViewDomain(domain) {
    var full = wi.fullDomain;
    var span = Math.min(domain[1] - domain[0], full[1] - full[0]);
    span = Math.max(span, MIN_SPAN_MS);
    var lo = domain[0], hi = lo + span;
    if (lo < full[0]) { lo = full[0]; hi = lo + span; }
    if (hi > full[1]) { hi = full[1]; lo = hi - span; }
    return [lo, hi];
  }

  function wiLocalXFromClientX(svg, clientX) {
    var rect = svg.getBoundingClientRect();
    var scale = wi.width / rect.width;
    return (clientX - rect.left) * scale - MARGIN.left;
  }

  function wiZoomAtLocalX(panel, localX, factor) {
    var frac = Math.max(0, Math.min(1, localX / panel.innerW));
    var cursorT = wi.viewDomain[0] + frac * (wi.viewDomain[1] - wi.viewDomain[0]);
    var span = (wi.viewDomain[1] - wi.viewDomain[0]) * factor;
    var lo = cursorT - frac * span, hi = lo + span;
    wi.viewDomain = wiClampViewDomain([lo, hi]);
    wiRenderAll();
  }

  function wiAttachInteraction(panel) {
    var svg = panel.svg;
    var pointers = {};
    var dragState = null;
    var pinchState = null;

    function activeIds() { return Object.keys(pointers); }
    function distanceBetween(idA, idB) {
      var a = pointers[idA], b = pointers[idB];
      return Math.hypot(a.x - b.x, a.y - b.y);
    }
    function midpointX(idA, idB) { return (pointers[idA].x + pointers[idB].x) / 2; }

    svg.addEventListener("pointerdown", function (evt) {
      evt.preventDefault();
      try { svg.setPointerCapture(evt.pointerId); } catch (e) { /* nice-to-have */ }
      pointers[evt.pointerId] = { x: evt.clientX, y: evt.clientY };
      var ids = activeIds();
      if (ids.length === 2) {
        dragState = null;
        pinchState = { ids: ids, lastDist: distanceBetween(ids[0], ids[1]) };
        svg.classList.remove("dragging");
        panel.tapStart = null;
      } else if (ids.length === 1) {
        pinchState = null;
        svg.classList.add("dragging");
        dragState = { startX: evt.clientX, startDomain: wi.viewDomain.slice() };
        panel.tapStart = { x: evt.clientX, y: evt.clientY };
      }
    });

    svg.addEventListener("pointermove", function (evt) {
      if (!(evt.pointerId in pointers)) { wiHandleHover(panel, evt); return; }
      pointers[evt.pointerId] = { x: evt.clientX, y: evt.clientY };
      if (panel.tapStart && Math.hypot(evt.clientX - panel.tapStart.x, evt.clientY - panel.tapStart.y) > TAP_MAX_MOVE_PX) {
        panel.tapStart = null;
      }
      if (pinchState) {
        evt.preventDefault();
        var ids = pinchState.ids;
        if (!(ids[0] in pointers) || !(ids[1] in pointers)) return;
        var dist = distanceBetween(ids[0], ids[1]);
        if (pinchState.lastDist > 0 && dist > 0) {
          wiZoomAtLocalX(panel, wiLocalXFromClientX(svg, midpointX(ids[0], ids[1])), pinchState.lastDist / dist);
        }
        pinchState.lastDist = dist;
        return;
      }
      if (dragState) {
        evt.preventDefault();
        var scale = wi.width / svg.getBoundingClientRect().width;
        var pxPerMs = panel.innerW / (dragState.startDomain[1] - dragState.startDomain[0]);
        var dxPx = (evt.clientX - dragState.startX) * scale;
        var dtMs = dxPx / pxPerMs;
        wi.viewDomain = wiClampViewDomain([dragState.startDomain[0] - dtMs, dragState.startDomain[1] - dtMs]);
        wiRenderAll();
        return;
      }
      wiHandleHover(panel, evt);
    });

    function endPointer(evt) {
      try { svg.releasePointerCapture(evt.pointerId); } catch (e) { /* already released */ }
      delete pointers[evt.pointerId];
      var ids = activeIds();
      var wasTap = evt.type === "pointerup" && !pinchState && panel.tapStart && ids.length === 0;
      if (pinchState) {
        if (ids.length < 2) {
          pinchState = null;
          if (ids.length === 1) {
            dragState = { startX: pointers[ids[0]].x, startDomain: wi.viewDomain.slice() };
            svg.classList.add("dragging");
          } else {
            svg.classList.remove("dragging");
          }
        }
      } else if (dragState && ids.length === 0) {
        dragState = null;
        svg.classList.remove("dragging");
      }
      if (wasTap) {
        panel.tapStart = null;
        wiSelectPoint(panel, evt);
      }
    }
    svg.addEventListener("pointerup", endPointer);
    svg.addEventListener("pointercancel", endPointer);
    svg.addEventListener("pointerleave", function () {
      if (wi.pinned) return;
      wi.panels.forEach(function (p) { if (p.crosshair) p.crosshair.setAttribute("visibility", "hidden"); });
      els.tooltip.hidden = true;
    });

    svg.addEventListener("wheel", function (evt) {
      evt.preventDefault();
      var factor = evt.deltaY > 0 ? 1.15 : 1 / 1.15;
      wiZoomAtLocalX(panel, wiLocalXFromClientX(svg, evt.clientX), factor);
    }, { passive: false });
  }

  function wiHandleHover(panel, evt) {
    if (wi.pinned) return;
    wiShowReadingsAt(wiTMsFromClientX(panel, evt.clientX), evt);
  }

  function wiSelectPoint(panel, evt) {
    wi.pinned = true;
    wiShowReadingsAt(wiTMsFromClientX(panel, evt.clientX), evt);
  }

  function wiTMsFromClientX(panel, clientX) {
    var localX = wiLocalXFromClientX(panel.svg, clientX);
    var clampedX = Math.max(0, Math.min(panel.innerW, localX));
    return wi.viewDomain[0] + (clampedX / panel.innerW) * (wi.viewDomain[1] - wi.viewDomain[0]);
  }

  // The series is hourly and evenly spaced starting at wi.nowMs, so the
  // exact hour index is a direct round-trip -- no need for a nearest-point
  // scan, and this stays correct however the view is panned/zoomed.
  function wiHourIndexFromMs(tMs) {
    var idx = Math.round((tMs - wi.nowMs) / 3600000);
    return Math.max(0, Math.min(wi.hours, idx));
  }

  function wiShowReadingsAt(tMs, evt) {
    wi.panels.forEach(function (p) {
      var cx = p.x ? p.x(tMs) : -10;
      if (p.crosshair) {
        p.crosshair.setAttribute("x1", cx);
        p.crosshair.setAttribute("x2", cx);
        p.crosshair.setAttribute("visibility", "visible");
      }
    });
    var idx = wiHourIndexFromMs(tMs);
    wiShowTooltip(evt, idx);
  }

  // Tapping a point pins this tooltip (same gesture as every other chart on
  // the site) rather than injecting immediately -- injecting is a
  // deliberate second click on one of the buttons below, so just exploring
  // the chart never risks silently overwriting a scenario.
  function wiShowTooltip(evt, idx) {
    var low = wi.lowSeries[idx], high = wi.highSeries[idx];
    els.tooltip.innerHTML = "";
    var timeRow = document.createElement("div");
    timeRow.className = "row";
    var k0 = document.createElement("span"); k0.className = "k"; k0.textContent = "Time";
    var v0 = document.createElement("span"); v0.className = "v"; v0.textContent = fmtDateTime(Date.parse(low.t));
    timeRow.appendChild(k0); timeRow.appendChild(v0);
    els.tooltip.appendChild(timeRow);

    [["Low", low], ["High", high]].forEach(function (pair) {
      var row = document.createElement("div");
      row.className = "row";
      var k = document.createElement("span"); k.className = "k"; k.textContent = pair[0];
      var v = document.createElement("span"); v.className = "v";
      v.textContent = "PSI " + Math.round(pair[1].psi) + " / PM " + pair[1].latest1h.toFixed(1);
      row.appendChild(k); row.appendChild(v);
      els.tooltip.appendChild(row);
    });

    if (idx < wi.hours) {
      var btnRow = document.createElement("div");
      btnRow.className = "row tooltip-actions";
      [["low", "Edit low →"], ["high", "Edit high →"]].forEach(function (pair) {
        var btn = document.createElement("button");
        btn.type = "button";
        btn.textContent = pair[1];
        btn.addEventListener("pointerdown", function (e) { e.stopPropagation(); });
        btn.addEventListener("click", function (e) {
          e.stopPropagation();
          wiInjectAt(pair[0], idx);
        });
        btnRow.appendChild(btn);
      });
      els.tooltip.appendChild(btnRow);
    }

    els.tooltip.hidden = false;
    // Measured, not the ~220px other tabs' simpler tooltips assume -- the
    // button row can make this one noticeably wider, and a hardcoded guess
    // was clipping it off the left edge on narrow screens.
    var ttW = els.tooltip.getBoundingClientRect().width || 220;
    var left = evt.clientX + 14;
    if (left + ttW > window.innerWidth) left = evt.clientX - ttW - 14;
    left = Math.max(8, left);
    els.tooltip.style.left = left + "px";
    els.tooltip.style.top = (evt.clientY + 14) + "px";
  }

  function wiBuildTable() {
    els.tableBodyWhatif.innerHTML = "";
    for (var i = 0; i < wi.lowSeries.length; i++) {
      var tr = document.createElement("tr");
      appendCell(tr, fmtDateTime(Date.parse(wi.lowSeries[i].t)));
      appendCell(tr, wi.lowSeries[i].latest1h.toFixed(1));
      appendCell(tr, wi.highSeries[i].latest1h.toFixed(1));
      appendCell(tr, Math.round(wi.lowSeries[i].psi));
      appendCell(tr, Math.round(wi.highSeries[i].psi));
      els.tableBodyWhatif.appendChild(tr);
    }
  }

  function wiInit() {
    function go() {
      wiPopulateDefaults();
      wiCalculate();
    }
    if (state.data) {
      go();
    } else {
      els.subtitleWhatif.textContent = "Waiting for live data to load…";
      onLiveDataReady.push(go);
    }
  }

  // ---------------------------------------------------------------------
  // Tabs + init
  // ---------------------------------------------------------------------
  function activateTab(name) {
    if (name === activeTab) return;
    activeTab = name;

    // Dismiss any pinned tooltip/crosshair from the tab being left.
    state.pinned = false;
    estate.pinned = false;
    h15.pinned = false;
    wi.pinned = false;
    els.tooltip.hidden = true;
    state.panels.forEach(function (p) { if (p.crosshair) p.crosshair.setAttribute("visibility", "hidden"); });
    estate.panels.forEach(function (p) { if (p.crosshair) p.crosshair.setAttribute("visibility", "hidden"); });
    h15.panels.forEach(function (p) { if (p.crosshair) p.crosshair.setAttribute("visibility", "hidden"); });
    wi.panels.forEach(function (p) { if (p.crosshair) p.crosshair.setAttribute("visibility", "hidden"); });

    document.getElementById("tab-panel-live").hidden = name !== "live";
    document.getElementById("tab-panel-episodes").hidden = name !== "episodes";
    document.getElementById("tab-panel-h15").hidden = name !== "h15";
    document.getElementById("tab-panel-whatif").hidden = name !== "whatif";
    els.tabBtnLive.classList.toggle("active", name === "live");
    els.tabBtnEpi.classList.toggle("active", name === "episodes");
    els.tabBtnH15.classList.toggle("active", name === "h15");
    els.tabBtnWhatif.classList.toggle("active", name === "whatif");
    els.tabBtnLive.setAttribute("aria-selected", name === "live" ? "true" : "false");
    els.tabBtnEpi.setAttribute("aria-selected", name === "episodes" ? "true" : "false");
    els.tabBtnH15.setAttribute("aria-selected", name === "h15" ? "true" : "false");
    els.tabBtnWhatif.setAttribute("aria-selected", name === "whatif" ? "true" : "false");

    if (name === "live") {
      measureWidth();
      renderAll();
    } else if (name === "episodes") {
      if (!estate.initialized) {
        estate.initialized = true;
        epiInit();
      } else {
        epiMeasureWidth();
        epiRenderAll();
      }
    } else if (name === "h15") {
      if (!h15.initialized) {
        h15.initialized = true;
        h15Init();
      } else {
        h15MeasureWidth();
        h15RenderAll();
      }
    } else if (name === "whatif") {
      if (!wi.initialized) {
        wi.initialized = true;
        wiInit();
      } else {
        wiMeasureWidth();
        wiRenderAll();
      }
    }
  }

  document.addEventListener("DOMContentLoaded", init);

  function init() {
    els.subtitle = document.getElementById("subtitle");
    els.legend = document.getElementById("legend");
    els.tooltip = document.getElementById("tooltip");
    els.resetBtn = document.getElementById("reset-view");
    els.refreshBtn = document.getElementById("refresh-page");
    els.toggleTableBtn = document.getElementById("toggle-table");
    els.tableWrap = document.getElementById("table-wrap");
    els.tableBody = document.getElementById("data-table-body");
    els.statusTableBody = document.getElementById("status-table-body");
    els.tabBtnLive = document.getElementById("tab-btn-live");
    els.tabBtnEpi = document.getElementById("tab-btn-episodes");
    els.tabBtnH15 = document.getElementById("tab-btn-h15");
    els.subtitleEpi = document.getElementById("subtitle-epi");
    els.regionFilterEpi = document.getElementById("region-filter-epi");
    els.selectEpi = document.getElementById("episode-select");
    els.metaEpi = document.getElementById("episode-meta");
    els.resetBtnEpi = document.getElementById("reset-view-epi");
    els.toggleTableBtnEpi = document.getElementById("toggle-table-epi");
    els.tableWrapEpi = document.getElementById("table-wrap-epi");
    els.tableBodyEpi = document.getElementById("data-table-body-epi");
    els.subtitleH15 = document.getElementById("subtitle-h15");
    els.legendH15 = document.getElementById("legend-h15");
    els.resetBtnH15 = document.getElementById("reset-view-h15");
    els.toggleTableBtnH15 = document.getElementById("toggle-table-h15");
    els.tableWrapH15 = document.getElementById("table-wrap-h15");
    els.tableBodyH15 = document.getElementById("data-table-body-h15");
    els.tabBtnWhatif = document.getElementById("tab-btn-whatif");
    els.subtitleWhatif = document.getElementById("subtitle-whatif");
    els.wiPsiLow = document.getElementById("whatif-psi-low");
    els.wiPsiHigh = document.getElementById("whatif-psi-high");
    els.wiPmLow = document.getElementById("whatif-pm-low");
    els.wiPmHigh = document.getElementById("whatif-pm-high");
    els.whatifSubmit = document.getElementById("whatif-submit");
    els.whatifError = document.getElementById("whatif-error");
    els.resetBtnWhatif = document.getElementById("reset-view-whatif");
    els.toggleTableBtnWhatif = document.getElementById("toggle-table-whatif");
    els.tableWrapWhatif = document.getElementById("table-wrap-whatif");
    els.tableBodyWhatif = document.getElementById("data-table-body-whatif");

    els.refreshBtn.addEventListener("click", function () {
      location.reload();
    });
    els.toggleTableBtn.addEventListener("click", function () {
      var hidden = els.tableWrap.hidden;
      els.tableWrap.hidden = !hidden;
      els.toggleTableBtn.textContent = hidden ? "Hide data table" : "View data table";
    });
    els.resetBtn.addEventListener("click", function () {
      state.viewDomain = defaultViewDomain();
      state.pinned = false;
      els.tooltip.hidden = true;
      renderAll();
    });
    els.tabBtnLive.addEventListener("click", function () { activateTab("live"); });
    els.tabBtnEpi.addEventListener("click", function () { activateTab("episodes"); });
    els.tabBtnH15.addEventListener("click", function () { activateTab("h15"); });
    els.tabBtnWhatif.addEventListener("click", function () { activateTab("whatif"); });
    els.selectEpi.addEventListener("change", function () { epiSelectEpisode(els.selectEpi.value); });
    els.resetBtnEpi.addEventListener("click", function () {
      if (!estate.episode) return;
      estate.viewDomain = estate.fullDomain.slice();
      estate.pinned = false;
      els.tooltip.hidden = true;
      epiRenderAll();
    });
    els.toggleTableBtnEpi.addEventListener("click", function () {
      var hidden = els.tableWrapEpi.hidden;
      els.tableWrapEpi.hidden = !hidden;
      els.toggleTableBtnEpi.textContent = hidden ? "Hide data table" : "View data table";
    });
    els.resetBtnH15.addEventListener("click", function () {
      if (!h15.data) return;
      h15.viewDomain = h15.fullDomain.slice();
      h15.pinned = false;
      els.tooltip.hidden = true;
      h15RenderAll();
    });
    els.toggleTableBtnH15.addEventListener("click", function () {
      var hidden = els.tableWrapH15.hidden;
      els.tableWrapH15.hidden = !hidden;
      els.toggleTableBtnH15.textContent = hidden ? "Hide data table" : "View data table";
    });
    els.whatifSubmit.addEventListener("click", wiCalculate);
    els.resetBtnWhatif.addEventListener("click", function () {
      if (!wi.fullDomain) return;
      wi.viewDomain = wi.fullDomain.slice();
      wi.pinned = false;
      els.tooltip.hidden = true;
      wiRenderAll();
    });
    els.toggleTableBtnWhatif.addEventListener("click", function () {
      var hidden = els.tableWrapWhatif.hidden;
      els.tableWrapWhatif.hidden = !hidden;
      els.toggleTableBtnWhatif.textContent = hidden ? "Hide data table" : "View data table";
    });

    window.addEventListener("resize", debounce(function () {
      if (activeTab === "live") {
        measureWidth();
        renderAll();
      } else if (activeTab === "episodes" && estate.initialized) {
        epiMeasureWidth();
        epiRenderAll();
      } else if (activeTab === "h15" && h15.initialized) {
        h15MeasureWidth();
        h15RenderAll();
      } else if (activeTab === "whatif" && wi.initialized) {
        wiMeasureWidth();
        wiRenderAll();
      }
    }, 150));

    // Tapping/clicking outside the live chart-card dismisses its pinned
    // tooltip; each panel's own pointerdown/up handlers above decide
    // whether a click inside counts as a tap or a drag.
    document.addEventListener("pointerdown", function (evt) {
      if (!state.pinned) return;
      if (evt.target.closest && evt.target.closest("#tab-panel-live")) return;
      state.pinned = false;
      els.tooltip.hidden = true;
      state.panels.forEach(function (p) { if (p.crosshair) p.crosshair.setAttribute("visibility", "hidden"); });
    });
    document.addEventListener("pointerdown", function (evt) {
      if (!estate.pinned) return;
      if (evt.target.closest && evt.target.closest("#tab-panel-episodes")) return;
      estate.pinned = false;
      els.tooltip.hidden = true;
      estate.panels.forEach(function (p) { if (p.crosshair) p.crosshair.setAttribute("visibility", "hidden"); });
    });
    document.addEventListener("pointerdown", function (evt) {
      if (!h15.pinned) return;
      if (evt.target.closest && evt.target.closest("#tab-panel-h15")) return;
      h15.pinned = false;
      els.tooltip.hidden = true;
      h15.panels.forEach(function (p) { if (p.crosshair) p.crosshair.setAttribute("visibility", "hidden"); });
    });
    document.addEventListener("pointerdown", function (evt) {
      if (!wi.pinned) return;
      if (evt.target.closest && evt.target.closest("#tab-panel-whatif")) return;
      wi.pinned = false;
      els.tooltip.hidden = true;
      wi.panels.forEach(function (p) { if (p.crosshair) p.crosshair.setAttribute("visibility", "hidden"); });
    });

    fetch("data.json", { cache: "no-store" })
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (data) {
        state.data = data;
        var allT = [];
        Object.keys(data.regions).forEach(function (region) {
          var p = data.regions[region];
          p.history.forEach(function (h) { allT.push(Date.parse(h.t)); });
          p.projection.forEach(function (pt) { allT.push(Date.parse(pt.t)); });
        });
        if (!allT.length) throw new Error("no data points in data.json");
        state.fullDomain = [Math.min.apply(null, allT), Math.max.apply(null, allT)];
        state.viewDomain = defaultViewDomain();
        computeYDomains();

        var asOfMs = Math.max.apply(null, Object.keys(data.regions).map(function (r) {
          return Date.parse(data.regions[r].as_of);
        }));
        els.subtitle.textContent = "Latest reading: " + fmtSGT(asOfMs, { year: "numeric", month: "short", day: "2-digit" }) + " SGT";

        buildLegend(data.colors);
        buildStatusTable(data);
        buildTable(data);
        measureWidth();
        buildPanel("chart-pm25", false);
        buildPanel("chart-psi", true);
        renderAll();

        // Let the What-if Projection tab populate its defaults/first
        // calculation if it was opened before this fetch resolved.
        onLiveDataReady.forEach(function (fn) { fn(); });
        onLiveDataReady = [];
      })
      .catch(function (err) {
        els.subtitle.textContent = "Failed to load data.json";
        var p = document.createElement("p");
        p.className = "empty-state";
        p.textContent = "Could not load dashboard data (" + err.message + "). This page needs to be served over http(s), not opened as a local file.";
        document.querySelector("#tab-panel-live .chart-card").replaceWith(p);
      });
  }
})();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
