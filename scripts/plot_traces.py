"""Plot per-device movement traces from the GPS pings on a static map.

Picks a few active devices on a chosen day, connects their time-ordered pings
into a line, and draws each trace over the DIY village-boundary basemap with
HH:MM labels at every ping — so you can visually verify that devices are
actually moving (and where / when).

Usage
-----
    python scripts/plot_traces.py --day 2021-10-30 --n 5 --layout single --out outputs/traces
    python scripts/plot_traces.py --maids <id1> <id2>   # specific devices
    python scripts/plot_traces.py --layout grid        # per-device zoomed panels

``--layout single`` (default) overlays all traces in different colours on one
map covering the whole DIY region; ``--layout grid`` draws one zoomed panel
per device with HH:MM at every ping.

Requires the village boundaries GeoPackage (default:
``data/geo/batas_desa_diy.gpkg``).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from shapely.geometry import LineString, Point

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mobility import clean, config, io, metrics  # noqa: E402

# Distinct colours for overlaid traces (single-map layout).
TRACE_COLORS = ["#C44E52", "#4C72B0", "#55A868", "#F5C542", "#8172B3",
                "#CC79A7", "#D55E00", "#0072B2", "#8C6D31", "#2E7D32"]


def _span_km(lons, lats) -> float:
    """Bounding-box diagonal in km (cheap movement proxy)."""
    return metrics.haversine_km(lons.min(), lats.min(), lons.max(), lats.max())


def _pick_maids(df, n: int, min_pings: int) -> list[str]:
    """Auto-select the most-mobile devices on the day (enough pings + spread)."""
    stats = df.groupby("maid").agg(
        n=("timestamp", "size"),
        lon_min=("longitude", "min"), lon_max=("longitude", "max"),
        lat_min=("latitude", "min"), lat_max=("latitude", "max"),
    )
    stats = stats[stats["n"] >= min_pings].copy()
    stats["span"] = [metrics.haversine_km(r.lon_min, r.lat_min, r.lon_max, r.lat_max)
                     for r in stats.itertuples()]
    top = stats.nlargest(n, "span").index.tolist()
    return top


def _pick_maids_mix(df, n: int, min_pings: int) -> list[str]:
    """Pick a variety: 1 long-distance + a mix of medium/short (commuters)."""
    stats = df.groupby("maid").agg(
        n=("timestamp", "size"),
        lon_min=("longitude", "min"), lon_max=("longitude", "max"),
        lat_min=("latitude", "min"), lat_max=("latitude", "max"),
    )
    stats = stats[stats["n"] >= min_pings].copy()
    stats["span"] = [metrics.haversine_km(r.lon_min, r.lat_min, r.lon_max, r.lat_max)
                      for r in stats.itertuples()]

    def band(s):
        return "long" if s >= 25 else ("med" if s >= 5 else "short")

    stats["band"] = stats["span"].map(band)
    long_ = stats[stats["band"] == "long"].nlargest(1, "span")
    med = stats[stats["band"] == "med"].nlargest(10, "span")
    short = stats[stats["band"] == "short"].nlargest(10, "span")

    chosen = long_.index.tolist()
    for i in range(max(len(med), len(short))):
        if len(chosen) >= n:
            break
        if i < len(med):
            chosen.append(med.index[i])
        if len(chosen) >= n:
            break
        if i < len(short):
            chosen.append(short.index[i])
    return chosen[:n]


def _village_of(points: gpd.GeoDataFrame, villages: gpd.GeoDataFrame) -> list[str]:
    """Village name (NAMOBJ) containing each point, or '' if outside DIY."""
    joined = gpd.sjoin(points, villages[["geometry", "NAMOBJ"]], how="left",
                       predicate="within")
    return joined["NAMOBJ"].fillna("").tolist()


def _draw_trace(ax, one: pd.DataFrame, color: str, label_every: int | None = None):
    """Draw one device's time-ordered path on ``ax`` in ``color``.

    Always labels the start (S) and end (E) times; optionally labels interior
    points every ``label_every`` pings.
    """
    one = one.sort_values("timestamp").reset_index(drop=True)
    lons = one["longitude"].to_numpy()
    lats = one["latitude"].to_numpy()
    line = LineString(list(zip(lons, lats)))
    gpd.GeoSeries([line], crs="EPSG:4326").plot(ax=ax, color=color, lw=2.0)
    ax.scatter(lons, lats, color=color, s=16, zorder=5)

    t0, t1 = one["datetime"].iloc[0], one["datetime"].iloc[-1]
    ax.annotate(f"S {t0:%H:%M}", xy=(lons[0], lats[0]), fontsize=8,
                color=color, fontweight="bold", xytext=(4, 4),
                textcoords="offset points")
    ax.annotate(f"E {t1:%H:%M}", xy=(lons[-1], lats[-1]), fontsize=8,
                color=color, fontweight="bold", xytext=(4, 4),
                textcoords="offset points")
    if label_every:
        for i in range(label_every, len(one) - 1, label_every):
            ax.annotate(one["datetime"].iloc[i].strftime("%H:%M"),
                        xy=(lons[i], lats[i]), fontsize=6.5, alpha=0.8,
                        xytext=(3, 3), textcoords="offset points")


def _single_map(d, chosen, villages, out, day) -> Path:
    """All traces overlaid on one map covering the whole DIY area."""
    fig, ax = plt.subplots(figsize=(12, 11))
    villages.boundary.plot(ax=ax, color="grey", lw=0.35, alpha=0.6)

    handles = []
    for i, maid in enumerate(chosen):
        color = TRACE_COLORS[i % len(TRACE_COLORS)]
        one = d[d["maid"] == maid]
        _draw_trace(ax, one, color)  # S / E time labels only
        span = _span_km(one["longitude"], one["latitude"])
        label = (f"{maid[:8]}… · {len(one)} pings · {span:.1f} km · "
                 f"{one['datetime'].iloc[0]:%H:%M}-{one['datetime'].iloc[-1]:%H:%M}")
        handles.append((plt.Line2D([0], [0], color=color, lw=2.5), label))

    ax.set_aspect("equal")
    b = villages.total_bounds
    ax.set_xlim(b[0] - 0.02, b[2] + 0.02)
    ax.set_ylim(b[1] - 0.02, b[3] + 0.02)
    ax.set_xlabel("Longitude"); ax.set_ylabel("Latitude")
    ax.set_title(f"Individual movement traces — {day} "
                 f"({len(chosen)} devices, whole DIY)")
    ax.legend(*zip(*handles), loc="upper left", fontsize=8, framealpha=0.9)
    ax.grid(alpha=0.2)
    fig.tight_layout()
    out_path = out / f"traces_{day}_all.png"
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path


def _grid_map(d, chosen, villages, out, day) -> Path:
    """Per-device zoomed subplots (previous behaviour, HH:MM at each ping)."""
    ncol = 2
    nrow = int(np.ceil(len(chosen) / ncol))
    fig, axes = plt.subplots(nrow, ncol, figsize=(13, 6 * nrow))
    axes = np.asarray(axes).ravel()

    for ax, maid in zip(axes, chosen):
        one = d[d["maid"] == maid]
        lons, lats = one["longitude"].to_numpy(), one["latitude"].to_numpy()
        span = _span_km(one["longitude"], one["latitude"])
        pad = 0.01
        vis = villages.cx[lons.min()-pad:lons.max()+pad, lats.min()-pad:lats.max()+pad]
        vis.boundary.plot(ax=ax, color="grey", lw=0.4, alpha=0.7)
        _draw_trace(ax, one, "#C44E52", label_every=max(1, len(one) // 25))

        pings_gdf = gpd.GeoDataFrame(
            geometry=[Point(x, y) for x, y in zip(lons, lats)], crs="EPSG:4326")
        v = _village_of(pings_gdf, villages)
        if v[0]:
            ax.annotate(f"start: {v[0]}", xy=(lons[0], lats[0]), fontsize=8,
                        color="#2E7D32", fontweight="bold", xytext=(4, 4),
                        textcoords="offset points")
        if v[-1] and v[-1] != v[0]:
            ax.annotate(f"end: {v[-1]}", xy=(lons[-1], lats[-1]), fontsize=8,
                        color="#C62828", fontweight="bold", xytext=(4, 4),
                        textcoords="offset points")

        ax.set_aspect("equal")
        ax.set_title(f"{maid[:8]}… · {day} · {len(one)} pings · "
                     f"{span:.1f} km span", fontsize=9)
        ax.set_xlabel("Longitude"); ax.set_ylabel("Latitude")
        ax.grid(alpha=0.2)

    for ax in axes[len(chosen):]:
        ax.axis("off")
    fig.suptitle(f"Individual movement traces — {day} (village boundaries)",
                 fontsize=13)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    out_path = out / f"traces_{day}.png"
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path


def build(mobility_path: Path, day: str, maids: list[str] | None, n: int,
          min_pings: int, boundaries: Path, out: Path,
          layout: str = "single", pick: str = "top",
          max_speed_kph: float = 120.0) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)

    print(f"loading {mobility_path} ...")
    df = io.load_mobility(mobility_path)
    d = df[df["date"] == pd.Timestamp(day)].copy()
    print(f"  {len(d):,} pings on {day}")

    if max_speed_kph > 0:
        before = len(d)
        d = clean.filter_speed_outliers(d, max_kph=max_speed_kph)
        print(f"  speed filter (>{max_speed_kph:.0f} km/h): dropped "
              f"{before - len(d):,} / {before:,} pings")

    if maids:
        chosen = [m for m in maids if m in set(d["maid"])]
    elif pick == "mix":
        chosen = _pick_maids_mix(d, n=n, min_pings=min_pings)
    else:
        chosen = _pick_maids(d, n=n, min_pings=min_pings)
    print(f"  tracing {len(chosen)} devices")

    villages = gpd.read_file(boundaries)
    print(f"  basemap: {len(villages)} village polygons ({villages.crs})")

    if layout == "single":
        path = _single_map(d, chosen, villages, out, day)
    else:
        path = _grid_map(d, chosen, villages, out, day)
    print(f"  wrote {path.name}")
    return [path]


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mobility", default=str(config.MOBILITY_PARQUET))
    ap.add_argument("--day", default="2021-10-30")
    ap.add_argument("--n", type=int, default=5, help="devices to auto-pick")
    ap.add_argument("--maids", nargs="+", default=None, help="specific maids")
    ap.add_argument("--min-pings", type=int, default=10)
    ap.add_argument("--boundaries", default="data/geo/batas_desa_diy.gpkg")
    ap.add_argument("--layout", default="single", choices=["single", "grid"],
                    help="single = all traces on one whole-DIY map; "
                         "grid = per-device zoomed subplots")
    ap.add_argument("--pick", default="top", choices=["top", "mix"],
                    help="top = most-mobile devices; mix = 1 long-distance + "
                         "commuters/stationary (default top)")
    ap.add_argument("--max-speed-kph", type=float, default=120.0,
                    help="drop pings implying > this speed (0 = no filter)")
    ap.add_argument("--out", default="outputs/traces")
    args = ap.parse_args()

    build(Path(args.mobility), args.day, args.maids, args.n, args.min_pings,
          Path(args.boundaries), Path(args.out), layout=args.layout,
          pick=args.pick, max_speed_kph=args.max_speed_kph)


if __name__ == "__main__":
    main()
