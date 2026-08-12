"""Build spatial aggregates (H3 grids + OD flows) and cache them to Parquet.

This is the "heavy" spatial step and is deliberately kept **outside** the
notebooks. It reads the cleaned mobility parquet, aggregates it into
H3-hexagon density grids and origin–destination flows, and writes small
Parquet files that notebooks/other scripts can plot quickly.

OD outputs (beyond the device-day trips and directed flows):
- ``concentration_*``           : daily Gini / HHI of the H3 grid
- ``od_flows_*``                : + ``od_distance_km`` (cell centroid distance)
- ``od_corridor_change_*``      : per-corridor % change vs baseline
- ``od_flows_district_*``       : district-level flows (when ``--people``)
- ``od_net_flows_district_*``   : net directional flow per district pair

Optionally renders a static density map (PNG) — no interactive mapping needed.

Usage
-----
    python scripts/prepare_spatial.py \
        --mobility data/parquet/mobility.parquet \
        --res 8 --out data/processed --plot outputs/maps

    # with district-level OD + corridor change:
    python scripts/prepare_spatial.py --people data/parquet/people.parquet \
        --baseline-days 3 --plot outputs/maps

    # quick smoke test on a sample:
    python scripts/prepare_spatial.py --sample 500000 --plot outputs/maps
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mobility import config, homes, io, od, spatial  # noqa: E402


def build(mobility_path: Path, res: int, out_dir: Path, sample: int | None,
          plot_dir: Path | None, baseline_days: int | list | None = None,
          people_path: Path | None = None, level: str = "place1") -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"loading {mobility_path} ...")
    t0 = time.perf_counter()
    df = io.load_mobility(mobility_path)
    if sample:
        df = df.sample(n=sample, random_state=42)
    print(f"  {len(df):,} pings in {time.perf_counter()-t0:.1f}s")

    # ---- H3 grid (per day) ------------------------------------------------#
    t0 = time.perf_counter()
    grid = spatial.aggregate_grid(df, res=res, time_bucket="date")
    grid_path = out_dir / f"h3_grid_r{res}_daily.parquet"
    grid.to_parquet(grid_path, index=False)
    print(f"  h3 grid: {len(grid):,} (date, cell) rows -> {grid_path.name} "
          f"in {time.perf_counter()-t0:.1f}s")

    # ---- Concentration (Gini / HHI) per day -------------------------------#
    t0 = time.perf_counter()
    conc = spatial.concentration(grid, value_col="count", group_cols=["date"])
    conc_path = out_dir / f"concentration_r{res}.parquet"
    conc.to_parquet(conc_path, index=False)
    print(f"  concentration: {len(conc):,} days (hhi/gini) -> "
          f"{conc_path.name} in {time.perf_counter()-t0:.1f}s")

    # ---- Origin–destination flows (per device per day) -------------------#
    t0 = time.perf_counter()
    od_dev = od.device_day_od(df, res=res)
    od_path = out_dir / f"od_device_day_r{res}.parquet"
    od_dev.to_parquet(od_path, index=False)

    flows = od.flow_distance(od.aggregate_od(od_dev))
    flows_path = out_dir / f"od_flows_r{res}.parquet"
    flows.to_parquet(flows_path, index=False)
    print(f"  OD: {len(od_dev):,} device-day trips, {len(flows):,} directed "
          f"flows (+od_distance_km) -> {od_path.name}, {flows_path.name} in "
          f"{time.perf_counter()-t0:.1f}s")

    # ---- Corridor change vs baseline --------------------------------------#
    if baseline_days is not None:
        t0 = time.perf_counter()
        corr = od.corridor_change(flows, baseline_days=baseline_days)
        corr_path = out_dir / f"od_corridor_change_r{res}.parquet"
        corr.to_parquet(corr_path, index=False)
        print(f"  corridor change: {len(corr):,} (date, pair) rows -> "
              f"{corr_path.name} in {time.perf_counter()-t0:.1f}s")

    # ---- District-level OD ------------------------------------------------#
    if people_path is not None and people_path.exists():
        t0 = time.perf_counter()
        people = io.load_people(people_path)
        hs = homes.detect_homes(df, res=res)  # home cells for the cell->district map
        cell_map = od.cell_district_map(hs, people, level=level)
        labeled = od.label_flows(flows, cell_map, origin_label=f"origin_{level}",
                                 dest_label=f"dest_{level}")
        dist_flows = od.aggregate_od_by_place(labeled,
                                              origin_col=f"origin_{level}",
                                              dest_col=f"dest_{level}")
        dist_path = out_dir / f"od_flows_district_r{res}.parquet"
        dist_flows.to_parquet(dist_path, index=False)

        net = od.net_flows(dist_flows, origin_col=f"origin_{level}",
                           dest_col=f"dest_{level}")
        net_path = out_dir / f"od_net_flows_district_r{res}.parquet"
        net.to_parquet(net_path, index=False)
        print(f"  district OD ({level}): {len(dist_flows):,} flows, "
              f"{len(net):,} net pairs -> {dist_path.name}, {net_path.name} in "
              f"{time.perf_counter()-t0:.1f}s")

    # ---- Optional static map ----------------------------------------------#
    if plot_dir is not None:
        plot_dir = Path(plot_dir)
        plot_dir.mkdir(parents=True, exist_ok=True)
        _plot_hexbin(df, plot_dir / "density_hexbin.png", title="GPS ping density")
        _plot_h3_grid(grid, res, plot_dir / "h3_grid_top.png", top_k=50_000)
        print(f"  maps -> {plot_dir}")


def _plot_hexbin(df, out: Path, title: str, gridsize: int = 200) -> None:
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(10, 9))
    hb = ax.hexbin(df["longitude"], df["latitude"], gridsize=gridsize,
                   cmap="magma", bins="log", mincnt=1)
    fig.colorbar(hb, ax=ax, shrink=0.8, label="log10(pings/bin)")
    ax.set_aspect("equal")
    ax.set_xlabel("Longitude"); ax.set_ylabel("Latitude"); ax.set_title(title)
    fig.tight_layout(); fig.savefig(out, dpi=150); plt.close(fig)


def _plot_h3_grid(grid, res: int, out: Path, top_k: int) -> None:
    import matplotlib.pyplot as plt
    import numpy as np
    top = grid.nlargest(top_k, "count")
    lats, lons = spatial.grid_centroids(top["h3"])
    fig, ax = plt.subplots(figsize=(10, 9))
    sc = ax.scatter(lons, lats, c=np.log10(top["count"]),
                    s=4, cmap="magma", alpha=0.8)
    fig.colorbar(sc, ax=ax, shrink=0.8, label="log10(pings)")
    ax.set_aspect("equal")
    ax.set_xlabel("Longitude"); ax.set_ylabel("Latitude")
    ax.set_title(f"H3 r{res} cell density (top {len(top):,} cells)")
    fig.tight_layout(); fig.savefig(out, dpi=150); plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mobility", default=str(config.MOBILITY_PARQUET),
                    help="cleaned mobility parquet "
                         f"(default: {config.MOBILITY_PARQUET})")
    ap.add_argument("--res", type=int, default=config.H3_RES_GRID)
    ap.add_argument("--out", default=str(config.PROCESSED_DIR))
    ap.add_argument("--sample", type=int, default=None,
                    help="random sample size (for quick tests)")
    ap.add_argument("--plot", default=None,
                    help="dir for static map PNGs (optional)")
    ap.add_argument("--baseline-days", default="3",
                    help="baseline = first N distinct dates (int) or a "
                         "comma-separated date list (default '3'; 'none' to skip)")
    ap.add_argument("--people", default=None,
                    help="people-graph parquet to build district-level OD")
    ap.add_argument("--level", default="place1", choices=["place1", "place2"],
                    help="admin level for district OD: place1=regency, "
                         "place2=district (default place1)")
    args = ap.parse_args()

    mob_path = Path(args.mobility)
    if not mob_path.exists():  # fall back to the legacy October-2021 parquet
        mob_path = config.DEFAULT_MOBILITY_PARQUET
        print(f"note: {args.mobility} not found, using {mob_path}")

    baseline = None
    if args.baseline_days.lower() != "none":
        baseline = int(args.baseline_days) if args.baseline_days.isdigit() \
            else [d.strip() for d in args.baseline_days.split(",")]

    build(mob_path, args.res, Path(args.out), args.sample,
          Path(args.plot) if args.plot else None,
          baseline_days=baseline,
          people_path=Path(args.people) if args.people else None,
          level=args.level)


if __name__ == "__main__":
    main()
