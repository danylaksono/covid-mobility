"""Render static summary plots from the prepared data (data/processed).

Reads the cached Parquet outputs (full-data run) and writes PNGs under
``outputs/plots/``. Lightweight — load + matplotlib only. Reusable after any
re-run (e.g. when new months are ingested).

Usage
-----
    python scripts/plot_summary.py --out outputs/plots
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mobility import config, io, spatial  # noqa: E402

P = config.PROCESSED_DIR

BLUE = "#4C72B0"; ORANGE = "#DD8452"; GREEN = "#55A868"
YELLOW = "#F5C542"; RED = "#C44E52"; PURPLE = "#8172B3"


def _save(fig, out: Path, name: str) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    path = out / name
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"  wrote {path.name}")
    return path


def _dates(x: pd.Series) -> list[str]:
    return [d.strftime("%d %b") for d in x]


def temporal_daily(out: Path):
    d = io.load_mobility(config.MOBILITY_PARQUET)
    daily = d.groupby("date").agg(pings=("maid", "size"), devices=("maid", "nunique"))
    labels = [x.strftime("%d %b") for x in daily.index]
    fig, axes = plt.subplots(1, 2, figsize=(15, 4.2))
    axes[0].bar(range(len(daily)), daily["pings"].values / 1e6, color=BLUE)
    axes[0].set_xticks(range(len(daily))); axes[0].set_xticklabels(labels, rotation=45)
    axes[0].set_title("GPS pings per day"); axes[0].set_ylabel("Pings (millions)")
    axes[1].bar(range(len(daily)), daily["devices"].values / 1e3, color=ORANGE)
    axes[1].set_xticks(range(len(daily))); axes[1].set_xticklabels(labels, rotation=45)
    axes[1].set_title("Active devices per day"); axes[1].set_ylabel("Devices (thousands)")
    _save(fig, out, "1_temporal_daily.png")


def spatial_hexbin(out: Path):
    d = io.load_mobility(config.MOBILITY_PARQUET)
    fig, ax = plt.subplots(figsize=(9, 8))
    hb = ax.hexbin(d["longitude"], d["latitude"], gridsize=220, cmap="magma",
                   bins="log", mincnt=1)
    fig.colorbar(hb, ax=ax, shrink=0.8, label="log10(pings/bin)")
    ax.set_aspect("equal"); ax.set_title("GPS ping density — Oct 2021 (full data)")
    ax.set_xlabel("Longitude"); ax.set_ylabel("Latitude")
    _save(fig, out, "2_spatial_hexbin.png")


def spatial_h3grid(out: Path):
    path = P / "h3_grid_r8_daily.parquet"
    if not path.exists():
        return
    grid = pd.read_parquet(path)
    top = grid.nlargest(50_000, "count")
    lats, lons = spatial.grid_centroids(top["h3"])
    fig, ax = plt.subplots(figsize=(9, 8))
    sc = ax.scatter(lons, lats, c=np.log10(top["count"]), s=4, cmap="magma", alpha=0.8)
    fig.colorbar(sc, ax=ax, shrink=0.8, label="log10(pings)")
    ax.set_aspect("equal")
    ax.set_title("H3 r8 cell density — top cells (full data)")
    ax.set_xlabel("Longitude"); ax.set_ylabel("Latitude")
    _save(fig, out, "3_spatial_h3grid.png")


def metrics_stay_home(out: Path):
    path = P / "mobility_index_r8.parquet"
    if not path.exists():
        return
    mi = pd.read_parquet(path)
    labels = _dates(mi["date"])
    fig, axes = plt.subplots(1, 2, figsize=(15, 4.2))
    axes[0].plot(mi["date"], mi["stay_at_home"] * 100, marker="o", ms=4, color=RED)
    axes[0].set_title("Stay-at-home rate (%)"); axes[0].set_ylabel("%")
    axes[0].set_xticks(mi["date"]); axes[0].set_xticklabels(labels, rotation=45)
    axes[1].plot(mi["date"], mi["stay_at_home_pct_change"], marker="o", ms=4, color=BLUE)
    axes[1].axhline(0, color="grey", lw=1)
    axes[1].set_title("Stay-at-home: % change vs baseline"); axes[1].set_ylabel("%")
    axes[1].set_xticks(mi["date"]); axes[1].set_xticklabels(labels, rotation=45)
    _save(fig, out, "4_metrics_stay_home.png")


def concentration(out: Path):
    path = P / "concentration_r8.parquet"
    if not path.exists():
        return
    c = pd.read_parquet(path)
    labels = _dates(c["date"])
    fig, axes = plt.subplots(1, 2, figsize=(15, 4.2))
    axes[0].plot(c["date"], c["hhi"], marker="o", ms=4, color=BLUE)
    axes[0].set_title("Herfindahl index (HHI)"); axes[0].set_ylabel("HHI")
    axes[0].set_xticks(c["date"]); axes[0].set_xticklabels(labels, rotation=45)
    axes[1].plot(c["date"], c["gini"], marker="o", ms=4, color=GREEN)
    axes[1].set_title("Gini coefficient"); axes[1].set_ylabel("Gini")
    axes[1].set_xticks(c["date"]); axes[1].set_xticklabels(labels, rotation=45)
    _save(fig, out, "5_concentration.png")


def od_trip_length(out: Path):
    path = P / "od_flows_r8.parquet"
    if not path.exists():
        return
    f = pd.read_parquet(path)
    fig, axes = plt.subplots(1, 2, figsize=(15, 4.2))
    ml = f.groupby("date")["od_distance_km"].mean()
    axes[0].plot(ml.index, ml.values, marker="o", ms=4, color=PURPLE)
    axes[0].set_title("Mean OD trip length (km)"); axes[0].set_ylabel("km")
    axes[0].set_xticks(ml.index); axes[0].set_xticklabels(_dates(ml.index), rotation=45)
    axes[1].hist(f["od_distance_km"].clip(upper=30), bins=40, color=PURPLE, alpha=0.8)
    axes[1].set_title("OD trip-length distribution"); axes[1].set_xlabel("km (clipped at 30)")
    _save(fig, out, "6_od_trip_length.png")


def od_top_corridors(out: Path):
    path = P / "od_flows_district_r8.parquet"
    if not path.exists():
        return
    d = pd.read_parquet(path)
    inter = d[d["origin_place1"] != d["dest_place1"]]
    top = (inter.groupby(["origin_place1", "dest_place1"])["n_pings"]
           .sum().nlargest(6).index)
    fig, ax = plt.subplots(figsize=(12, 4.5))
    for o, dd in top:
        s = inter[(inter["origin_place1"] == o) & (inter["dest_place1"] == dd)]
        ax.plot(s["date"], s["n_pings"] / 1e3, marker="o", ms=3, label=f"{o} -> {dd}")
    ax.set_title("Top inter-regency corridors (daily pings, thousands)")
    ax.set_ylabel("pings (thousands)"); ax.legend(fontsize=8)
    ax.set_xticks(s["date"]); ax.set_xticklabels(_dates(s["date"]), rotation=45)
    _save(fig, out, "7_od_top_corridors.png")


def meeting_index(out: Path):
    mid_path = P / "meeting_index_daily_r8_1h.parquet"
    crow_path = P / "crowding_r8_1h.parquet"
    if not mid_path.exists():
        return
    mid = pd.read_parquet(mid_path)
    crow = pd.read_parquet(crow_path) if crow_path.exists() else None
    labels = _dates(mid["date"])
    fig, axes = plt.subplots(1, 2, figsize=(15, 4.2))
    axes[0].plot(mid["date"], mid["meeting_index"] / 1e6, marker="o", ms=4, color=RED)
    axes[0].set_title("Daily meeting index (millions of pairwise co-locations)")
    axes[0].set_ylabel("meetings (millions)")
    axes[0].set_xticks(mid["date"]); axes[0].set_xticklabels(labels, rotation=45)
    if crow is not None:
        axes[1].plot(crow["bucket"], crow["cells_n10"], marker="o", ms=3, color=PURPLE)
        axes[1].set_title("Crowded cells (>=10 devices / hour)")
        axes[1].set_ylabel("cells"); axes[1].tick_params(axis="x", rotation=45)
    _save(fig, out, "8_meeting_index.png")


def people_graph(out: Path):
    people = io.load_people(config.DEFAULT_PEOPLE_PARQUET)
    prof = people.drop_duplicates("maid")
    fig, axes = plt.subplots(1, 3, figsize=(16, 4))
    sex = prof["sex"].value_counts()
    axes[0].bar(sex.index, sex.values / 1e3, color=[BLUE, ORANGE])
    axes[0].set_title("By sex (thousands)"); axes[0].tick_params(axis="x", rotation=30)
    inten = prof["intensity"].value_counts()
    axes[1].bar(inten.index, inten.values / 1e3, color=[GREEN, YELLOW, RED])
    axes[1].set_title("By intensity (thousands)"); axes[1].tick_params(axis="x", rotation=30)
    kab = prof["place1"].value_counts()
    axes[2].barh(kab.index[::-1], kab.values[::-1] / 1e3, color=BLUE)
    axes[2].set_title("By regency (thousands)"); axes[2].set_xlabel("devices (thousands)")
    _save(fig, out, "9_people_graph.png")


def _stitch_report(plot_dir: Path, report_path: Path) -> Path:
    """Combine all individual PNGs into a single vertical report sheet."""
    files = sorted(plot_dir.glob("*.png"))
    if not files:
        return report_path
    imgs = [Image.open(f) for f in files]
    gap = 24
    max_w = max(im.width for im in imgs)
    total_h = sum(im.height for im in imgs) + gap * (len(imgs) - 1)
    canvas = Image.new("RGB", (max_w, total_h), "white")
    y = 0
    for im in imgs:
        x = (max_w - im.width) // 2
        canvas.paste(im, (x, y))
        y += im.height + gap
    canvas.save(report_path)
    print(f"  wrote {report_path.name} (combined report, {len(imgs)} panels)")
    return report_path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="outputs/plots")
    ap.add_argument("--report", default=None, nargs="?", const="outputs/report_summary.png",
                    help="also write a combined report image (default outputs/report_summary.png)")
    args = ap.parse_args()
    out = Path(args.out)

    print("rendering summary plots ...")
    temporal_daily(out)
    spatial_hexbin(out)
    spatial_h3grid(out)
    metrics_stay_home(out)
    concentration(out)
    od_trip_length(out)
    od_top_corridors(out)
    meeting_index(out)
    people_graph(out)

    if args.report:
        _stitch_report(out, Path(args.report))
    print(f"\nplots written to {out.resolve()}")


if __name__ == "__main__":
    main()
