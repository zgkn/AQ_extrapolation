"""Builds docs/index.html: a Folium map of Singapore showing each region's
current PSI/PM2.5 and flat-PM2.5 projection, for hosting on GitHub Pages.

Region markers sit at approximate representative points for NEA's five
reporting regions (not official boundaries -- just enough to place a marker
sensibly on the map). "national" isn't plotted as a marker (it would sit
right on top of "central"); it's shown in the header banner instead.

CAVEATS (see aq_lib.py for the PSI-modeling one):
  - The projection assumes the latest 1-hr PM2.5 reading holds perfectly
    flat for up to 24h. Real air quality will not actually do this -- this
    is a simplification for a quick "if nothing changes" read, not a
    forecast.
"""
from __future__ import annotations

import csv
import html
import logging
import os
import sys

import folium

sys.path.insert(0, os.path.dirname(__file__))
from aq_lib import HISTORY_PATH, REGIONS, compute_payload, parse_ts  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("build_map")

OUTPUT_PATH = "docs/index.html"
SINGAPORE_CENTER = (1.3521, 103.8198)

# Approximate representative points for each region -- for marker placement
# only, not official NEA boundary centroids.
REGION_COORDS = {
    "north": (1.4360, 103.7860),
    "south": (1.2650, 103.8200),
    "east": (1.3400, 103.9500),
    "west": (1.3450, 103.7000),
    "central": (1.3350, 103.8200),
}

# (max_psi_inclusive, color, band label) -- standard NEA PSI bands.
PSI_BANDS = [
    (50, "#2ecc71", "Good"),
    (100, "#f1c40f", "Moderate"),
    (200, "#e67e22", "Unhealthy"),
    (300, "#e74c3c", "Very Unhealthy"),
    (float("inf"), "#7f1734", "Hazardous"),
]


def band_for(psi: float):
    for limit, color, label in PSI_BANDS:
        if psi <= limit:
            return color, label
    return PSI_BANDS[-1][1], PSI_BANDS[-1][2]


def fmt_time(iso: str) -> str:
    return parse_ts(iso).strftime("%a %d %b, %H:%M")


def threshold_lines(thresholds: list[dict]) -> str:
    lines = []
    for th in thresholds:
        if th["reachable"] is True:
            eta = fmt_time(th["eta"])
            lines.append(f"PSI {th['value']}: ETA {html.escape(eta)} (+{th['hours']:.1f}h)")
        elif th["reachable"] is False:
            lines.append(f"PSI {th['value']}: not reachable in 24h flat (needs X≈{th['needed_flat_pm25']:.0f}µg/m³)")
        else:
            lines.append(f"PSI {th['value']}: n/a (no baseline yet)")
    return "<br>".join(lines)


def popup_html(region: str, payload: dict) -> str:
    latest_psi = next((h["psi"] for h in reversed(payload["history"]) if h["psi"] is not None), None)
    latest_pm25_1h = next((h["pm25_1h"] for h in reversed(payload["history"]) if h["pm25_1h"] is not None), None)
    latest_pm25_24h = next((h["pm25_24h"] for h in reversed(payload["history"]) if h["pm25_24h"] is not None), None)
    source = next((h["pm25_24h_source"] for h in reversed(payload["history"]) if h["pm25_24h_source"]), None)

    psi_str = f"{latest_psi:.0f}" if latest_psi is not None else "n/a"
    _, band_label = band_for(latest_psi) if latest_psi is not None else ("", "n/a")
    pm25_1h_str = f"{latest_pm25_1h:.1f}" if latest_pm25_1h is not None else "n/a"
    pm25_24h_str = f"{latest_pm25_24h:.1f}" if latest_pm25_24h is not None else "n/a"

    return f"""
    <div style="font-family: system-ui, sans-serif; font-size: 13px; min-width: 220px;">
      <b>{html.escape(region.capitalize())}</b><br>
      As of {html.escape(fmt_time(payload['as_of']))} SGT<hr style="margin:4px 0;">
      PSI (24-hr): <b>{psi_str}</b> ({html.escape(band_label)})<br>
      PM2.5 (1-hr): {pm25_1h_str} µg/m³<br>
      PM2.5 (24-hr avg): {pm25_24h_str} µg/m³
      {f' <span style="color:#888;">({html.escape(source)})</span>' if source else ''}
      <hr style="margin:4px 0;">
      <div style="font-size:12px;">{threshold_lines(payload['thresholds'])}</div>
    </div>
    """


def load_region_rows() -> dict[str, list[dict]]:
    by_region: dict[str, list[dict]] = {r: [] for r in REGIONS}
    if not os.path.exists(HISTORY_PATH):
        raise SystemExit(f"{HISTORY_PATH} does not exist -- run scripts/fetch_data.py first")
    with open(HISTORY_PATH, newline="") as f:
        for row in csv.DictReader(f):
            if row["region"] in by_region:
                by_region[row["region"]].append(row)
    for rows in by_region.values():
        rows.sort(key=lambda r: r["timestamp"])
    return by_region


def build_legend() -> str:
    rows = "".join(
        f'<div style="display:flex;align-items:center;gap:6px;margin:2px 0;">'
        f'<span style="width:12px;height:12px;border-radius:50%;background:{color};display:inline-block;"></span>'
        f'<span>{label} (≤{limit if limit != float("inf") else "500+"})</span></div>'
        for limit, color, label in PSI_BANDS
    )
    return f"""
    <div style="position: fixed; bottom: 20px; left: 20px; z-index: 9999;
                background: white; padding: 10px 14px; border-radius: 8px;
                box-shadow: 0 1px 4px rgba(0,0,0,0.3); font-family: system-ui, sans-serif;
                font-size: 12px; color: #222;">
      <div style="font-weight:600; margin-bottom: 4px;">PSI band</div>
      {rows}
    </div>
    """


def build_header(national_payload: dict | None) -> str:
    if national_payload is not None:
        latest_psi = next((h["psi"] for h in reversed(national_payload["history"]) if h["psi"] is not None), None)
        latest_pm25 = next((h["pm25_1h"] for h in reversed(national_payload["history"]) if h["pm25_1h"] is not None), None)
        psi_str = f"{latest_psi:.0f}" if latest_psi is not None else "n/a"
        pm25_str = f"{latest_pm25:.1f}" if latest_pm25 is not None else "n/a"
        as_of = fmt_time(national_payload["as_of"])
        stats = f"National PSI (24-hr): <b>{psi_str}</b> &nbsp;|&nbsp; PM2.5 (1-hr): {pm25_str} µg/m³ &nbsp;|&nbsp; as of {html.escape(as_of)} SGT"
    else:
        stats = "No national data yet."
    return f"""
    <div style="position: fixed; top: 12px; left: 50%; transform: translateX(-50%); z-index: 9999;
                background: white; padding: 10px 20px; border-radius: 8px;
                box-shadow: 0 1px 4px rgba(0,0,0,0.3); font-family: system-ui, sans-serif;
                font-size: 13px; color: #222; text-align: center; max-width: 92vw;">
      <div style="font-weight:700; font-size: 15px; margin-bottom: 2px;">Singapore Haze Dashboard</div>
      <div>{stats}</div>
    </div>
    """


def build_footer() -> str:
    return """
    <div style="position: fixed; bottom: 4px; left: 50%; transform: translateX(-50%); z-index: 9999;
                background: rgba(255,255,255,0.85); padding: 4px 10px; border-radius: 6px;
                font-family: system-ui, sans-serif; font-size: 10px; color: #555; text-align: center;
                max-width: 90vw;">
      Model note: PSI here tracks only the PM2.5 sub-index (real PSI = max of six pollutants);
      the flat-PM2.5 projection is a simplification, not a forecast. Data: data.gov.sg.
    </div>
    """


def main() -> None:
    by_region = load_region_rows()
    payloads = {r: compute_payload(rows, r) for r, rows in by_region.items()}

    # Plain OpenStreetMap tiles -- no API key required (CartoDB's basemaps now
    # gate behind a key, which would break this on a public GitHub Pages site).
    m = folium.Map(location=SINGAPORE_CENTER, zoom_start=12, tiles="OpenStreetMap")

    plotted = 0
    for region, coord in REGION_COORDS.items():
        payload = payloads.get(region)
        if payload is None:
            log.warning("no data for region=%s -- skipping marker", region)
            continue
        latest_psi = next((h["psi"] for h in reversed(payload["history"]) if h["psi"] is not None), None)
        color = band_for(latest_psi)[0] if latest_psi is not None else "#999999"
        folium.CircleMarker(
            location=coord,
            radius=26,
            color=color,
            fill=True,
            fill_color=color,
            fill_opacity=0.75,
            weight=2,
            tooltip=f"{region.capitalize()}: PSI {latest_psi:.0f}" if latest_psi is not None else region.capitalize(),
            popup=folium.Popup(popup_html(region, payload), max_width=300),
        ).add_to(m)
        folium.map.Marker(
            location=coord,
            icon=folium.DivIcon(html=f"""
                <div style="font-size:13px;font-weight:700;color:white;text-align:center;
                            width:52px;transform:translate(-13px,-9px);">
                  {latest_psi:.0f}
                </div>""" if latest_psi is not None else ""),
        ).add_to(m)
        plotted += 1

    if plotted == 0:
        raise SystemExit("no region had data to plot -- refusing to write an empty map")

    m.get_root().html.add_child(folium.Element(build_header(payloads.get("national"))))
    m.get_root().html.add_child(folium.Element(build_legend()))
    m.get_root().html.add_child(folium.Element(build_footer()))

    docs_dir = os.path.dirname(OUTPUT_PATH)
    os.makedirs(docs_dir, exist_ok=True)
    m.save(OUTPUT_PATH)

    # Tell GitHub Pages to skip its default Jekyll build and serve docs/ as
    # plain static files -- without this, Pages runs the folder through
    # Jekyll's default theme processing, which errors out on a non-Jekyll
    # site (it expects e.g. a _config.yml / assets layout that isn't there).
    open(os.path.join(docs_dir, ".nojekyll"), "a").close()

    log.info("wrote %s (%d region marker(s))", OUTPUT_PATH, plotted)


if __name__ == "__main__":
    main()
