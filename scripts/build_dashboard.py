"""Builds a PNG dashboard from data/history.csv: past 24h of PSI + PM2.5 for
the "national" region, plus a flat-PM2.5 projection with threshold ETAs.

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
from aq_lib import (  # noqa: E402
    HISTORY_PATH,
    pm25_to_psi,
    projected_avg_pm25,
    parse_ts,
    time_to_threshold,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("build_dashboard")

REGION = "national"
THRESHOLDS = [100, 150, 200]
OUTPUT_PATH = "dashboard.png"


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


def to_float(s: str):
    if s is None or s == "":
        return None
    return float(s)


def main() -> None:
    rows = load_region_history(REGION)
    if not rows:
        raise SystemExit(f"no rows for region={REGION!r} in {HISTORY_PATH}")

    times = [parse_ts(r["timestamp"]) for r in rows]
    psi = [to_float(r["psi_twenty_four_hourly"]) for r in rows]
    pm25_1h = [to_float(r["pm25_one_hourly"]) for r in rows]
    pm25_24h = [to_float(r["pm25_twenty_four_hourly"]) for r in rows]

    now = times[-1]
    window_start = now - dt.timedelta(hours=24)
    plot_idx = [i for i, t in enumerate(times) if t >= window_start]
    if not plot_idx:
        plot_idx = list(range(len(times)))

    plot_times = [times[i] for i in plot_idx]
    plot_psi = [psi[i] for i in plot_idx]
    plot_pm25 = [pm25_1h[i] for i in plot_idx]

    # baseline B = latest available 24-hr avg PM2.5; latest X = latest 1-hr PM2.5
    baseline = next((pm25_24h[i] for i in range(len(rows) - 1, -1, -1) if pm25_24h[i] is not None), None)
    latest = next((pm25_1h[i] for i in range(len(rows) - 1, -1, -1) if pm25_1h[i] is not None), None)

    fig, ax_psi = plt.subplots(figsize=(11, 6))
    ax_pm25 = ax_psi.twinx()

    ax_psi.plot(plot_times, plot_psi, color="tab:red", linewidth=2, label="24-hr PSI (actual)")
    ax_pm25.plot(plot_times, plot_pm25, color="tab:blue", linewidth=1, alpha=0.6, label="1-hr PM2.5 (µg/m³)")

    if baseline is not None and latest is not None:
        proj_hours = [h for h in range(0, 25)]
        proj_times = [now + dt.timedelta(hours=h) for h in proj_hours]
        proj_pm25_avg = [projected_avg_pm25(baseline, latest, h) for h in proj_hours]
        proj_psi = [pm25_to_psi(v) for v in proj_pm25_avg]
        ax_psi.plot(proj_times, proj_psi, color="tab:red", linewidth=2, linestyle="--", label="Projected PSI (flat PM2.5)")

    for threshold in THRESHOLDS:
        ax_psi.axhline(threshold, color="gray", linestyle=":", linewidth=1)
        label = f"PSI {threshold}"
        if baseline is not None and latest is not None:
            result = time_to_threshold(baseline, latest, threshold)
            if result["reachable"]:
                eta = now + dt.timedelta(hours=result["hours"])
                label += f"\nETA {eta.strftime('%a %H:%M')} (+{result['hours']:.1f}h)"
            else:
                label += f"\nnot reachable in 24h flat\nneeds X≈{result['needed_flat_pm25']:.0f}µg/m³"
        # Anchor to the right edge in axes x-coords (data y-coords) so labels
        # don't collide with the historical PM2.5/PSI lines on the left.
        ax_psi.annotate(
            label,
            xy=(0.995, threshold),
            xycoords=("axes fraction", "data"),
            xytext=(-4, 4),
            textcoords="offset points",
            ha="right",
            va="bottom",
            fontsize=7.5,
            color="dimgray",
            bbox=dict(boxstyle="round,pad=0.2", facecolor="white", edgecolor="none", alpha=0.75),
        )

    ax_psi.set_ylabel("PSI (24-hr)", color="tab:red")
    ax_pm25.set_ylabel("PM2.5 (µg/m³, 1-hr)", color="tab:blue")
    ax_psi.set_xlabel("Time")
    ax_psi.set_title(f"Singapore Haze Dashboard -- {REGION} (as of {now.strftime('%Y-%m-%d %H:%M %Z')})")
    ax_psi.xaxis.set_major_formatter(mdates.DateFormatter("%a %H:%M"))
    fig.autofmt_xdate()

    lines1, labels1 = ax_psi.get_legend_handles_labels()
    lines2, labels2 = ax_pm25.get_legend_handles_labels()
    ax_psi.legend(lines1 + lines2, labels1 + labels2, loc="lower right", fontsize=8)

    fig.text(
        0.01,
        0.01,
        "Model note: PSI here tracks only the PM2.5 sub-index (real PSI = max of 6 pollutants); "
        "projection assumes flat PM2.5, not a forecast.",
        fontsize=7,
        color="gray",
    )

    fig.tight_layout()
    fig.savefig(OUTPUT_PATH, dpi=150)
    log.info("wrote %s", OUTPUT_PATH)


if __name__ == "__main__":
    main()
