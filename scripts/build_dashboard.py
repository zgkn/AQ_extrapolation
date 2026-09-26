"""Builds docs/index.html + docs/dashboard.png: time-series PM2.5 and PSI
for Singapore's five real reporting regions (north/south/east/west/central),
with a flat-PM2.5 projection on the PSI panel extrapolating toward the
100/150/200 thresholds.

Two stacked single-axis panels (PM2.5, then PSI) -- never one dual-axis
plot, which would invent a correlation between two differently-scaled
series. Each region gets a fixed categorical color (a validated
colorblind-safe order, never cycled), shared between both panels so a
region reads as the same color throughout.

CAVEATS (see aq_lib.py for the PSI-modeling one):
  - The projection assumes each region's latest 1-hr PM2.5 reading holds
    perfectly flat for up to 24h. Real air quality will not actually do
    this -- this is a simplification for a quick "if nothing changes"
    read, not a forecast.
"""
from __future__ import annotations

import csv
import datetime as dt
import logging
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(__file__))
from aq_lib import API_REGIONS, HISTORY_PATH, THRESHOLDS, compute_payload, parse_ts  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("build_dashboard")

DOCS_DIR = "docs"
CHART_PATH = os.path.join(DOCS_DIR, "dashboard.png")
HTML_PATH = os.path.join(DOCS_DIR, "index.html")

# Fixed categorical order -- the first five slots of a colorblind-validated
# eight-hue palette (worst adjacent CVD deltaE 9.1 light / 8.4 dark across
# the full eight; a fortiori across five). Assigned once per region and
# never reused/cycled/reordered by data.
REGION_COLORS = {
    "north": "#2a78d6",
    "south": "#eb6834",
    "east": "#1baf7a",
    "west": "#eda100",
    "central": "#e87ba4",
}
THRESHOLD_COLOR = "#898781"

# The chart is displayed at a fixed 820px CSS width (see write_html) rather
# than shrunk to fit a phone screen, but it's still smaller than a full
# desktop figure -- bump the default sizes up from matplotlib's defaults so
# axis ticks and labels stay legible at that width.
plt.rcParams.update({"font.size": 12, "axes.titlesize": 13, "axes.labelsize": 12})


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

    as_of = max(parse_ts(p["as_of"]) for p in payloads.values())

    fig, (ax_pm25, ax_psi) = plt.subplots(2, 1, figsize=(11, 8.3), sharex=True)

    for region in API_REGIONS:
        payload = payloads.get(region)
        if payload is None:
            continue
        color = REGION_COLORS[region]
        hist_t = [parse_ts(h["t"]) for h in payload["history"]]
        hist_pm25 = [h["pm25_1h"] for h in payload["history"]]
        hist_psi = [h["psi"] for h in payload["history"]]

        ax_pm25.plot(hist_t, hist_pm25, color=color, linewidth=2, label=region.capitalize())
        ax_psi.plot(hist_t, hist_psi, color=color, linewidth=2, label=region.capitalize())

        if payload["projection"]:
            proj_t = [parse_ts(p["t"]) for p in payload["projection"]]
            proj_psi = [p["psi"] for p in payload["projection"]]
            ax_psi.plot(proj_t, proj_psi, color=color, linewidth=2, linestyle="--", alpha=0.6)

    for threshold in THRESHOLDS:
        ax_psi.axhline(threshold, color=THRESHOLD_COLOR, linewidth=1)
        ax_psi.annotate(
            f"PSI {threshold}",
            xy=(0.995, threshold),
            xycoords=("axes fraction", "data"),
            xytext=(-4, 4),
            textcoords="offset points",
            ha="right",
            va="bottom",
            fontsize=10,
            color="#52514e",
            bbox=dict(boxstyle="round,pad=0.2", facecolor="white", edgecolor="none", alpha=0.75),
        )

    ax_pm25.set_ylabel("PM2.5 (µg/m³, 1-hr)")

    ax_psi.set_ylabel("PSI (24-hr)")
    ax_psi.set_xlabel("Time")
    ax_psi.set_title("Solid = actual, dashed = projected (flat 1-hr PM2.5 held constant)", fontsize=11, color="#52514e")
    ax_psi.xaxis.set_major_formatter(mdates.DateFormatter("%a %H:%M"))
    fig.autofmt_xdate()

    fig.suptitle(f"Singapore Haze -- as of {as_of.strftime('%Y-%m-%d %H:%M %Z')}", y=0.98, fontsize=15)
    handles, labels = ax_pm25.get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", bbox_to_anchor=(0.5, 0.925), ncol=len(handles), fontsize=11, frameon=False)

    fig.text(
        0.01,
        0.01,
        "Model note: PSI here tracks only the PM2.5 sub-index (real PSI = max of six pollutants); "
        "the dashed projection assumes each region's latest 1-hr PM2.5 holds flat, not a forecast.",
        fontsize=8.5,
        color="gray",
    )

    fig.tight_layout(rect=(0, 0.03, 1, 0.87))
    os.makedirs(DOCS_DIR, exist_ok=True)
    fig.savefig(CHART_PATH, dpi=150)
    log.info("wrote %s", CHART_PATH)

    write_html(as_of)

    # GitHub Pages runs a "Deploy from a branch" source through Jekyll by
    # default; .nojekyll tells it to serve docs/ as plain static files
    # instead (this isn't a Jekyll site, and the default build breaks on it).
    open(os.path.join(DOCS_DIR, ".nojekyll"), "a").close()


def write_html(as_of: dt.datetime) -> None:
    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Singapore Haze Dashboard</title>
<style>
  :root {{
    color-scheme: light;
    --bg: #f9f9f7;
    --surface: #fcfcfb;
    --ink: #0b0b0b;
    --muted: #52514e;
    --border: rgba(11,11,11,0.10);
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      color-scheme: dark;
      --bg: #0d0d0d;
      --surface: #1a1a19;
      --ink: #ffffff;
      --muted: #c3c2b7;
      --border: rgba(255,255,255,0.10);
    }}
  }}
  body {{
    margin: 0;
    background: var(--bg);
    color: var(--ink);
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  }}
  main {{
    max-width: 900px;
    margin: 0 auto;
    padding: 20px 16px 40px;
  }}
  h1 {{ font-size: 1.4rem; margin: 0 0 4px; }}
  .subtitle {{ color: var(--muted); font-size: 0.9rem; margin: 0 0 16px; }}
  .chart-card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 12px;
    /* The chart has 5 regions x 2 panels of fine detail (axis ticks, a
       5-entry legend, per-threshold labels) that turns to mush if the image
       is shrunk to fit a phone's width. Below the chart's own natural size,
       scroll/pinch to it at full size instead of force-shrinking everything
       into illegibility -- a wide chart, not a page, is what should scroll. */
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
  }}
  img {{ display: block; border-radius: 6px; width: 820px; max-width: none; }}
  @media (min-width: 900px) {{
    img {{ width: 100%; }}
  }}
  footer {{ margin-top: 16px; font-size: 0.78rem; color: var(--muted); line-height: 1.5; }}
</style>
</head>
<body>
<main>
  <header>
    <h1>Singapore Haze Dashboard</h1>
    <p class="subtitle">Latest reading: {as_of.strftime('%a %d %b %Y, %H:%M %Z')}</p>
  </header>
  <div class="chart-card">
    <img src="dashboard.png" alt="PM2.5 and PSI time series for Singapore's five regions, with a projected PSI extrapolation toward the 100/150/200 thresholds">
  </div>
  <footer>
    Model note: PSI here tracks only the PM2.5 sub-index (real PSI = max of six pollutant
    sub-indices: PM2.5, PM10, SO2, CO, O3, NO2), so on a day another pollutant dominates the
    real PSI can read higher than shown here. The dashed projection assumes each region's
    latest 1-hr PM2.5 reading holds perfectly flat for up to 24h -- a simplification for a
    quick "if nothing changes" read, not a forecast. Data: data.gov.sg.
  </footer>
</main>
</body>
</html>
"""
    with open(HTML_PATH, "w") as f:
        f.write(html)
    log.info("wrote %s", HTML_PATH)


if __name__ == "__main__":
    main()
