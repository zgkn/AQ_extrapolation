"""Builds a PNG dashboard from data/history.csv: past 24h of PSI + PM2.5 for
the "national" region, plus a flat-PM2.5 projection with threshold ETAs.

Rendered as two stacked single-axis panels (PSI, then PM2.5) rather than one
dual-axis plot -- a dual-axis chart invents an arbitrary correlation between
two differently-scaled series, so PSI and PM2.5 each get their own axis.

CAVEATS (see aq_lib.py for the PSI-modeling one):
  - The projection assumes the latest 1-hr PM2.5 reading holds perfectly
    flat for up to 24h. Real air quality will not actually do this -- this
    is a simplification for a quick "if nothing changes" read, not a
    forecast.
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
from aq_lib import HISTORY_PATH, compute_payload, parse_ts  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("build_dashboard")

REGION = "national"
OUTPUT_PATH = "dashboard.png"

PSI_COLOR = "#2a78d6"
PM25_COLOR = "#eb6834"


def load_region_history(region: str) -> list[dict]:
    if not os.path.exists(HISTORY_PATH):
        raise SystemExit(f"{HISTORY_PATH} does not exist -- run scripts/fetch_data.py first")
    rows = []
    with open(HISTORY_PATH, newline="") as f:
        for r in csv.DictReader(f):
            if r["region"] != region:
                continue
            rows.append(r)
    rows.sort(key=lambda r: r["timestamp"])
    return rows


def main() -> None:
    rows = load_region_history(REGION)
    payload = compute_payload(rows, REGION)
    if payload is None:
        raise SystemExit(f"no rows for region={REGION!r} in {HISTORY_PATH}")

    now = parse_ts(payload["as_of"])
    hist_t = [parse_ts(h["t"]) for h in payload["history"]]
    hist_psi = [h["psi"] for h in payload["history"]]
    hist_pm25 = [h["pm25_1h"] for h in payload["history"]]

    fig, (ax_psi, ax_pm25) = plt.subplots(2, 1, figsize=(11, 8), sharex=True)

    ax_psi.plot(hist_t, hist_psi, color=PSI_COLOR, linewidth=2, label="PSI (actual)")
    if payload["projection"]:
        proj_t = [parse_ts(p["t"]) for p in payload["projection"]]
        proj_psi = [p["psi"] for p in payload["projection"]]
        ax_psi.plot(proj_t, proj_psi, color=PSI_COLOR, linewidth=2, linestyle="--", alpha=0.6, label="PSI (projected, flat PM2.5)")

    for th in payload["thresholds"]:
        ax_psi.axhline(th["value"], color="#898781", linewidth=1)
        label = f"PSI {th['value']}"
        if th["reachable"] is True:
            eta = parse_ts(th["eta"])
            label += f"\nETA {eta.strftime('%a %H:%M')} (+{th['hours']:.1f}h)"
        elif th["reachable"] is False:
            label += f"\nnot reachable in 24h flat\nneeds X≈{th['needed_flat_pm25']:.0f}µg/m³"
        ax_psi.annotate(
            label,
            xy=(0.995, th["value"]),
            xycoords=("axes fraction", "data"),
            xytext=(-4, 4),
            textcoords="offset points",
            ha="right",
            va="bottom",
            fontsize=7.5,
            color="#52514e",
            bbox=dict(boxstyle="round,pad=0.2", facecolor="white", edgecolor="none", alpha=0.75),
        )

    ax_psi.set_ylabel("PSI (24-hr)")
    ax_psi.legend(loc="lower right", fontsize=8)
    ax_psi.set_title(f"Singapore Haze Dashboard -- {REGION} (as of {now.strftime('%Y-%m-%d %H:%M %Z')})")

    ax_pm25.plot(hist_t, hist_pm25, color=PM25_COLOR, linewidth=2)
    ax_pm25.set_ylabel("PM2.5 (µg/m³, 1-hr)")
    ax_pm25.set_xlabel("Time")
    ax_pm25.xaxis.set_major_formatter(mdates.DateFormatter("%a %H:%M"))
    fig.autofmt_xdate()

    fig.text(
        0.01,
        0.01,
        "Model note: PSI here tracks only the PM2.5 sub-index (real PSI = max of 6 pollutants); "
        "projection assumes flat PM2.5, not a forecast.",
        fontsize=7,
        color="gray",
    )

    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(OUTPUT_PATH, dpi=150)
    log.info("wrote %s", OUTPUT_PATH)


if __name__ == "__main__":
    main()
