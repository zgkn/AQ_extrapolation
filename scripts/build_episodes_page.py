"""Finds haze episodes (contiguous stretches where a region's 24-hr PSI was
above PSI_EPISODE_THRESHOLD) in data/episodes_history.csv and builds
docs/episodes/data.json + docs/episodes/index.html -- a second, independent
page (separate from the live docs/index.html dashboard) listing each episode
with a PM2.5 + PSI time-series chart padded BUFFER_HOURS before and after.

Run scripts/fetch_episodes_data.py first to populate
data/episodes_history.csv -- this script only reads it, it never hits the
network itself.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from aq_lib import API_REGIONS, parse_ts, to_float  # noqa: E402
from build_dashboard import REGION_COLORS  # noqa: E402
from fetch_episodes_data import EPISODES_HISTORY_PATH  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("build_episodes_page")

DOCS_DIR = "docs/episodes"
DATA_PATH = os.path.join(DOCS_DIR, "data.json")
HTML_PATH = os.path.join(DOCS_DIR, "index.html")

PSI_EPISODE_THRESHOLD = 100
BUFFER_HOURS = 24


def load_all_rows(path: str) -> dict[str, list[dict]]:
    by_region: dict[str, list[dict]] = {r: [] for r in API_REGIONS}
    if not os.path.exists(path):
        raise SystemExit(f"{path} does not exist -- run scripts/fetch_episodes_data.py first")
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            if row["region"] in by_region:
                by_region[row["region"]].append(row)
    for rows in by_region.values():
        rows.sort(key=lambda r: r["timestamp"])
    return by_region


def find_episodes(rows: list[dict]) -> list[dict]:
    """Contiguous runs of psi_twenty_four_hourly > PSI_EPISODE_THRESHOLD, in
    chronological order. A gap (missing/None reading, or a reading back at
    or below the threshold) ends the current run."""
    episodes: list[dict] = []
    current: dict | None = None
    for r in rows:
        psi = to_float(r["psi_twenty_four_hourly"])
        if psi is not None and psi > PSI_EPISODE_THRESHOLD:
            ts = parse_ts(r["timestamp"])
            if current is None:
                current = {"start": ts, "end": ts, "peak_psi": psi, "peak_time": ts}
            else:
                current["end"] = ts
                if psi > current["peak_psi"]:
                    current["peak_psi"] = psi
                    current["peak_time"] = ts
        elif current is not None:
            episodes.append(current)
            current = None
    if current is not None:
        episodes.append(current)
    return episodes


def build_episode_payload(region: str, episode: dict, rows: list[dict]) -> dict:
    window_start = episode["start"] - dt.timedelta(hours=BUFFER_HOURS)
    window_end = episode["end"] + dt.timedelta(hours=BUFFER_HOURS)
    series = []
    for r in rows:
        ts = parse_ts(r["timestamp"])
        if window_start <= ts <= window_end:
            series.append({
                "t": r["timestamp"],
                "pm25_1h": to_float(r["pm25_one_hourly"]),
                "psi": to_float(r["psi_twenty_four_hourly"]),
            })
    return {
        "region": region,
        "episode_start": episode["start"].isoformat(),
        "episode_end": episode["end"].isoformat(),
        "peak_psi": round(episode["peak_psi"], 1),
        "peak_time": episode["peak_time"].isoformat(),
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "series": series,
    }


def main() -> None:
    by_region = load_all_rows(EPISODES_HISTORY_PATH)

    all_ts = [parse_ts(r["timestamp"]) for rows in by_region.values() for r in rows]
    if not all_ts:
        raise SystemExit(f"{EPISODES_HISTORY_PATH} has no rows -- nothing to search")

    episodes = []
    for region in API_REGIONS:
        rows = by_region[region]
        found = find_episodes(rows)
        log.info("region=%s: %d episode(s) found above PSI %d", region, len(found), PSI_EPISODE_THRESHOLD)
        for episode in found:
            episodes.append(build_episode_payload(region, episode, rows))

    episodes.sort(key=lambda e: e["episode_start"], reverse=True)
    for i, ep in enumerate(episodes):
        ep["id"] = f"{ep['region']}-{i}"

    os.makedirs(DOCS_DIR, exist_ok=True)
    out = {
        "colors": REGION_COLORS,
        "threshold": PSI_EPISODE_THRESHOLD,
        "buffer_hours": BUFFER_HOURS,
        "search_start": min(all_ts).isoformat(),
        "search_end": max(all_ts).isoformat(),
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "episodes": episodes,
    }
    with open(DATA_PATH, "w") as f:
        json.dump(out, f, indent=2)
    log.info("wrote %s (%d episode(s) total)", DATA_PATH, len(episodes))

    write_html_once()
    open(os.path.join(DOCS_DIR, ".nojekyll"), "a").close()


def write_html_once() -> None:
    with open(HTML_PATH, "w") as f:
        f.write(INDEX_HTML)
    log.info("wrote %s", HTML_PATH)


INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Singapore Haze Episodes</title>
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
  h1 { font-size: 1.3rem; margin: 0 0 4px; }
  .subtitle { color: var(--muted); font-size: 0.9rem; margin: 0 0 4px; }
  .back-link { font-size: 0.82rem; margin: 0 0 12px; }
  .back-link a { color: var(--ink); }
  .refresh-btn {
    flex: 0 0 auto; display: inline-flex; align-items: center; gap: 5px;
    font: inherit; font-size: 0.8rem; padding: 5px 10px; border-radius: 6px;
    border: 1px solid var(--border); background: var(--surface); color: var(--ink); cursor: pointer;
  }
  .picker-row { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin: 10px 0; }
  .picker-row label { font-size: 0.82rem; color: var(--muted); }
  select#episode-select {
    font: inherit; font-size: 0.85rem; padding: 6px 8px; border-radius: 6px;
    border: 1px solid var(--border); background: var(--surface); color: var(--ink);
    flex: 1 1 auto; min-width: 0;
  }
  .toolbar {
    display: flex; align-items: center; justify-content: space-between; gap: 8px;
    margin-bottom: 8px; font-size: 0.8rem; color: var(--muted);
  }
  .toolbar button {
    font: inherit; font-size: 0.8rem; padding: 5px 10px; border-radius: 6px;
    border: 1px solid var(--border); background: var(--surface); color: var(--ink); cursor: pointer;
  }
  .episode-meta { font-size: 0.82rem; color: var(--muted); margin: 4px 0 10px; line-height: 1.5; }
  .episode-meta strong { color: var(--ink); }
  .chart-card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 10px 12px 4px; }
  .panel-title { font-size: 0.85rem; color: var(--muted); text-align: center; margin: 2px 0 4px; }
  svg.chart {
    width: 100%; height: auto; display: block; touch-action: none; cursor: grab;
    user-select: none; -webkit-user-select: none;
  }
  svg.chart.dragging { cursor: grabbing; }
  .axis-label { font-size: 10px; fill: var(--faint); }
  .threshold-label { font-size: 10px; fill: var(--muted); }
  .tooltip {
    position: fixed; pointer-events: none; background: var(--ink); color: var(--bg);
    font-size: 0.78rem; padding: 6px 9px; border-radius: 6px; line-height: 1.5; z-index: 20; white-space: nowrap;
  }
  .tooltip .row { display: flex; gap: 10px; justify-content: space-between; }
  .tooltip .row .k { opacity: 0.75; }
  .tooltip .row .v { font-weight: 600; font-variant-numeric: tabular-nums; }
  .table-section { margin-top: 10px; }
  .table-section button {
    font: inherit; font-size: 0.85rem; padding: 6px 12px; border-radius: 6px;
    border: 1px solid var(--border); background: var(--surface); color: var(--ink); cursor: pointer;
  }
  .table-wrap { margin-top: 10px; max-height: 340px; overflow: auto; border: 1px solid var(--border); border-radius: 10px; }
  table.data-table { width: 100%; border-collapse: collapse; font-size: 0.78rem; background: var(--surface); }
  table.data-table th, table.data-table td {
    text-align: right; padding: 5px 9px; border-bottom: 1px solid var(--grid);
    font-variant-numeric: tabular-nums; white-space: nowrap;
  }
  table.data-table th:first-child, table.data-table td:first-child { text-align: left; }
  table.data-table thead th { position: sticky; top: 0; background: var(--surface); color: var(--muted); font-variant-numeric: normal; }
  footer { margin-top: 16px; font-size: 0.78rem; color: var(--muted); line-height: 1.5; }
  .empty-state { color: var(--muted); font-size: 0.9rem; padding: 24px 0; text-align: center; }
</style>
</head>
<body>
<main>
  <header>
    <div>
      <h1>Singapore Haze Episodes</h1>
      <p class="subtitle" id="subtitle">Loading&hellip;</p>
    </div>
    <button class="refresh-btn" id="refresh-page" type="button" title="Reload the page">&#8635; Refresh</button>
  </header>
  <p class="back-link"><a href="../index.html">&larr; Back to the live dashboard</a></p>

  <div class="picker-row">
    <label for="episode-select">Episode</label>
    <select id="episode-select"></select>
  </div>
  <p class="episode-meta" id="episode-meta"></p>

  <div class="toolbar">
    <span>Drag to pan &middot; scroll or pinch to zoom &middot; tap a point for readings</span>
    <button id="reset-view" type="button">Reset view</button>
  </div>

  <div class="chart-card">
    <div class="panel-title">PM2.5 (&micro;g/m&sup3;, 1-hr)</div>
    <svg class="chart" id="chart-pm25"></svg>
    <div class="panel-title">PSI (24-hr) &mdash; shaded band marks the episode itself (above the threshold)</div>
    <svg class="chart" id="chart-psi"></svg>
  </div>

  <div class="table-section">
    <button id="toggle-table" type="button">View data table</button>
    <div class="table-wrap" id="table-wrap" hidden>
      <table class="data-table" id="data-table">
        <thead><tr><th>Time (SGT)</th><th>PSI</th><th>PM2.5 1h</th></tr></thead>
        <tbody id="data-table-body"></tbody>
      </table>
    </div>
  </div>

  <footer>
    An episode is a contiguous stretch where a region's 24-hr PSI (PM2.5 sub-index only -- see
    the live dashboard for the same caveat) was above the threshold shown below; each chart pads
    24h before the episode starts and 24h after it ends, for context. Data: data.gov.sg.
  </footer>
</main>

<div class="tooltip" id="tooltip" hidden></div>

<script>
(function () {
  "use strict";

  var SG_TZ = "Asia/Singapore";
  var SG_OFFSET_MS = 8 * 3600 * 1000;
  var MARGIN = { top: 10, right: 60, bottom: 6, left: 44 };
  var BOTTOM_AXIS_H = 24;
  var H_PM25 = 220, H_PSI = 250;
  var MIN_SPAN_MS = 3 * 3600 * 1000;
  var TAP_MAX_MOVE_PX = 8;
  var ONE_DAY_MS = 24 * 3600 * 1000;

  var state = {
    data: null,
    episode: null,      // the currently-selected episode object
    fullDomain: null,
    viewDomain: null,
    pm25YDomain: null,
    psiYDomain: null,
    panels: [],
    width: 860,
    pinned: false,
  };
  var els = {};

  document.addEventListener("DOMContentLoaded", init);

  function init() {
    els.subtitle = document.getElementById("subtitle");
    els.tooltip = document.getElementById("tooltip");
    els.resetBtn = document.getElementById("reset-view");
    els.refreshBtn = document.getElementById("refresh-page");
    els.toggleTableBtn = document.getElementById("toggle-table");
    els.tableWrap = document.getElementById("table-wrap");
    els.tableBody = document.getElementById("data-table-body");
    els.select = document.getElementById("episode-select");
    els.meta = document.getElementById("episode-meta");

    els.refreshBtn.addEventListener("click", function () { location.reload(); });
    els.toggleTableBtn.addEventListener("click", function () {
      var hidden = els.tableWrap.hidden;
      els.tableWrap.hidden = !hidden;
      els.toggleTableBtn.textContent = hidden ? "Hide data table" : "View data table";
    });
    els.resetBtn.addEventListener("click", function () {
      if (!state.episode) return;
      state.viewDomain = state.fullDomain.slice();
      state.pinned = false;
      els.tooltip.hidden = true;
      renderAll();
    });
    window.addEventListener("resize", debounce(function () {
      measureWidth();
      renderAll();
    }, 150));
    document.addEventListener("pointerdown", function (evt) {
      if (!state.pinned) return;
      if (evt.target.closest && evt.target.closest(".chart-card")) return;
      state.pinned = false;
      els.tooltip.hidden = true;
      state.panels.forEach(function (p) { if (p.crosshair) p.crosshair.setAttribute("visibility", "hidden"); });
    });
    els.select.addEventListener("change", function () {
      selectEpisode(els.select.value);
    });

    fetch("data.json", { cache: "no-store" })
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (data) {
        state.data = data;
        els.subtitle.textContent = "Searched " + fmtAxisDate(Date.parse(data.search_start)) + " to " +
          fmtAxisDate(Date.parse(data.search_end)) + " for PSI > " + data.threshold +
          " -- " + data.episodes.length + " episode(s) found";

        if (!data.episodes.length) {
          document.querySelector(".picker-row").hidden = true;
          document.querySelector(".toolbar").hidden = true;
          var p = document.createElement("p");
          p.className = "empty-state";
          p.textContent = "No episodes found -- every region stayed at or below PSI " + data.threshold + " for the whole search window.";
          document.querySelector(".chart-card").replaceWith(p);
          document.querySelector(".table-section").hidden = true;
          return;
        }

        buildSelect(data.episodes);
        measureWidth();
        buildPanel("chart-pm25", false);
        buildPanel("chart-psi", true);
        selectEpisode(data.episodes[0].id);
      })
      .catch(function (err) {
        els.subtitle.textContent = "Failed to load data.json";
        var p = document.createElement("p");
        p.className = "empty-state";
        p.textContent = "Could not load episode data (" + err.message + "). This page needs to be served over http(s), not opened as a local file.";
        document.querySelector(".chart-card").replaceWith(p);
      });
  }

  function debounce(fn, ms) {
    var t;
    return function () {
      clearTimeout(t);
      var args = arguments;
      t = setTimeout(function () { fn.apply(null, args); }, ms);
    };
  }

  function measureWidth() {
    var card = document.querySelector(".chart-card");
    state.width = Math.max(280, card.clientWidth - 24);
  }

  function fmtSGT(ms, opts) {
    return new Intl.DateTimeFormat("en-GB", Object.assign({
      timeZone: SG_TZ, weekday: "short", hour: "2-digit", minute: "2-digit", hour12: false
    }, opts || {})).format(new Date(ms));
  }

  function fmtAxisDate(ms) {
    return new Intl.DateTimeFormat("en-CA", { timeZone: SG_TZ, year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date(ms));
  }

  function buildSelect(episodes) {
    els.select.innerHTML = "";
    episodes.forEach(function (ep) {
      var opt = document.createElement("option");
      opt.value = ep.id;
      opt.textContent = capitalize(ep.region) + " — " + fmtSGT(Date.parse(ep.episode_start)) +
        " to " + fmtSGT(Date.parse(ep.episode_end)) + " (peak PSI " + Math.round(ep.peak_psi) + ")";
      els.select.appendChild(opt);
    });
  }

  function capitalize(s) { return s.charAt(0).toUpperCase() + s.slice(1); }

  function selectEpisode(id) {
    var ep = null;
    for (var i = 0; i < state.data.episodes.length; i++) {
      if (state.data.episodes[i].id === id) { ep = state.data.episodes[i]; break; }
    }
    if (!ep) return;
    els.select.value = id;
    state.episode = ep;
    state.pinned = false;
    els.tooltip.hidden = true;

    var allT = ep.series.map(function (pt) { return Date.parse(pt.t); });
    state.fullDomain = [Math.min.apply(null, allT), Math.max.apply(null, allT)];
    state.viewDomain = state.fullDomain.slice();
    computeYDomains(ep);

    els.meta.innerHTML = "<strong>" + capitalize(ep.region) + "</strong> &middot; episode " +
      fmtSGT(Date.parse(ep.episode_start), { year: "numeric", month: "short", day: "2-digit" }) + " to " +
      fmtSGT(Date.parse(ep.episode_end), { year: "numeric", month: "short", day: "2-digit" }) +
      " &middot; peak PSI " + Math.round(ep.peak_psi) + " at " + fmtSGT(Date.parse(ep.peak_time)) +
      " &middot; chart padded " + state.data.buffer_hours + "h before/after";

    buildTable(ep);
    renderAll();
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

  var MIN_PX_PER_TICK = 65;
  var STEP_CANDIDATES_MS = [15, 30, 60, 120, 180, 360, 720, 1440, 2880, 4320, 10080]
    .map(function (m) { return m * 60 * 1000; });
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

  function drawMarkers(container, points, x, y, xField, yField, color) {
    points.forEach(function (p) {
      var v = p[yField];
      if (v === null || v === undefined) return;
      container.appendChild(svgEl("circle", { cx: x(p[xField]).toFixed(1), cy: y(v).toFixed(1), r: 2.5, fill: color }));
    });
  }

  function computeYDomains(ep) {
    var pm25Vals = [0], psiVals = [0, state.data.threshold];
    ep.series.forEach(function (pt) {
      if (pt.pm25_1h !== null) pm25Vals.push(pt.pm25_1h);
      if (pt.psi !== null) psiVals.push(pt.psi);
    });
    var pm25Ticks = niceTicks(Math.min.apply(null, pm25Vals), Math.max.apply(null, pm25Vals), 4);
    var psiTicks = niceTicks(Math.min.apply(null, psiVals), Math.max.apply(null, psiVals), 4);
    state.pm25YDomain = [pm25Ticks[0], pm25Ticks[pm25Ticks.length - 1]];
    state.psiYDomain = [psiTicks[0], psiTicks[psiTicks.length - 1]];
  }

  function panelHeight(isPsi) { return isPsi ? H_PSI : H_PM25; }
  function panelInnerH(isPsi) { return panelHeight(isPsi) - MARGIN.top - MARGIN.bottom - (isPsi ? BOTTOM_AXIS_H : 0); }

  function buildPanel(id, isPsi) {
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
    var gridGroup = svgEl("g");
    var plot = svgEl("g", { "clip-path": "url(#" + clipId + ")" });
    var chromeGroup = svgEl("g");
    g.appendChild(gridGroup);
    g.appendChild(plot);
    g.appendChild(chromeGroup);
    var panel = { svg: svg, g: g, gridGroup: gridGroup, plot: plot, chromeGroup: chromeGroup, clipRect: clipRect, isPsi: isPsi, id: id };
    state.panels.push(panel);
    attachInteraction(panel);
    return panel;
  }

  function renderAll() {
    if (!state.episode) return;
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

    var ep = state.episode;
    var color = state.data.colors[ep.region] || "#2a78d6";

    // Shade the actual episode (above-threshold) span so the 24h buffer on
    // either side reads as context, not part of the episode itself.
    var epStartX = x(Date.parse(ep.episode_start));
    var epEndX = x(Date.parse(ep.episode_end));
    var bandX0 = Math.max(0, Math.min(epStartX, epEndX));
    var bandX1 = Math.min(innerW, Math.max(epStartX, epEndX));
    if (bandX1 > bandX0) {
      panel.plot.appendChild(svgEl("rect", { x: bandX0, y: 0, width: bandX1 - bandX0, height: innerH, fill: "var(--band)" }));
    }

    if (panel.isPsi) {
      var th = state.data.threshold;
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

  function attachInteraction(panel) {
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
        dragState = { startX: evt.clientX, startDomain: state.viewDomain.slice() };
        panel.tapStart = { x: evt.clientX, y: evt.clientY };
      }
    });

    svg.addEventListener("pointermove", function (evt) {
      if (!(evt.pointerId in pointers)) { handleHover(panel, evt); return; }
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
    if (state.pinned) return;
    showReadingsAt(tMsFromClientX(panel, evt.clientX), evt);
  }

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

    var series = state.episode.series;
    var nearest = null, bestDiff = Infinity;
    for (var i = 0; i < series.length; i++) {
      var diff = Math.abs(Date.parse(series[i].t) - tMs);
      if (diff < bestDiff) { bestDiff = diff; nearest = series[i]; }
    }
    if (!nearest) return;
    showTooltip(evt, nearest);
  }

  function showTooltip(evt, row) {
    els.tooltip.innerHTML = "";
    var tMs = Date.parse(row.t);
    var timeRow = document.createElement("div");
    timeRow.className = "row";
    var k0 = document.createElement("span"); k0.className = "k"; k0.textContent = "Time";
    var v0 = document.createElement("span"); v0.className = "v"; v0.textContent = fmtAxisDate(tMs) + " " + fmtSGT(tMs, { weekday: undefined });
    timeRow.appendChild(k0); timeRow.appendChild(v0);
    els.tooltip.appendChild(timeRow);

    var row2 = document.createElement("div");
    row2.className = "row";
    var k = document.createElement("span"); k.className = "k"; k.textContent = capitalize(state.episode.region);
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

  function buildTable(ep) {
    var rows = ep.series.slice().sort(function (a, b) { return Date.parse(b.t) - Date.parse(a.t); });
    els.tableBody.innerHTML = "";
    rows.forEach(function (r) {
      var tr = document.createElement("tr");
      appendCell(tr, fmtSGT(Date.parse(r.t), { year: "numeric", month: "short", day: "2-digit" }));
      appendCell(tr, r.psi === null ? "–" : Math.round(r.psi));
      appendCell(tr, r.pm25_1h === null ? "–" : r.pm25_1h.toFixed(1));
      els.tableBody.appendChild(tr);
    });
  }

  function appendCell(tr, text) {
    var td = document.createElement("td");
    td.textContent = text;
    tr.appendChild(td);
  }
})();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
