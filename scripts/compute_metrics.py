"""Compute home locations + per-device-day mobility metrics, cached to Parquet.

This produces the derived tables needed for the COVID mobility analysis and
the glyph-based visualisations:

- ``<out>/homes_r<res>.parquet``              : home H3 cell per device
- ``<out>/metrics_device_day_r<res>.parquet`` : n_pings, n_cells, n_trips,
  radius_km, max_dist_home_km, stay_at_home per (maid, date)
- ``<out>/mobility_index_r<res>.parquet``     : daily summary + % change vs a
  baseline window (Google/Apple mobility-report style)
- ``<out>/mobility_index_by_place1_r<res>.parquet`` : same, stratified by
  regency (only when ``--people`` is given)

Usage
-----
    python scripts/compute_metrics.py --out data/processed --res 8
    python scripts/compute_metrics.py --sample 500000   # quick smoke test
    python scripts/compute_metrics.py --people data/parquet/people.parquet \
        --baseline-days 3
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mobility import config, homes, io, metrics  # noqa: E402


def build(mobility_path: Path, res: int, out_dir: Path, sample: int | None,
          night_hours: tuple[int, int] | None = None,
          baseline_days: int | list | None = None,
          people_path: Path | None = None) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"loading {mobility_path} ...")
    t0 = time.perf_counter()
    df = io.load_mobility(mobility_path)
    if sample:
        df = df.sample(n=sample, random_state=42)
    print(f"  {len(df):,} pings in {time.perf_counter()-t0:.1f}s")

    # ---- home cells -------------------------------------------------------#
    t0 = time.perf_counter()
    hs = homes.detect_homes(df, res=res, night_hours=night_hours)
    homes_path = out_dir / f"homes_r{res}.parquet"
    hs.to_parquet(homes_path, index=False)
    print(f"  homes: {len(hs):,} devices -> {homes_path.name} "
          f"in {time.perf_counter()-t0:.1f}s")

    # ---- per-device-day metrics ------------------------------------------#
    t0 = time.perf_counter()
    m = metrics.device_day_metrics(df, res=res, homes=hs)
    metrics_path = out_dir / f"metrics_device_day_r{res}.parquet"
    m.to_parquet(metrics_path, index=False)
    print(f"  metrics: {len(m):,} device-days -> {metrics_path.name} "
          f"in {time.perf_counter()-t0:.1f}s")

    # ---- daily summary + change-from-baseline index ----------------------#
    if baseline_days is not None:
        t0 = time.perf_counter()
        daily = metrics.daily_summary(m)
        index = metrics.mobility_index(daily, baseline_days=baseline_days)
        index_path = out_dir / f"mobility_index_r{res}.parquet"
        index.to_parquet(index_path, index=False)
        print(f"  index: {len(index):,} days -> {index_path.name} "
              f"in {time.perf_counter()-t0:.1f}s")

        if people_path is not None and people_path.exists():
            prof = io.load_people(people_path)
            key = prof[["maid", "place1"]].drop_duplicates("maid")
            m_g = m.merge(key, on="maid", how="left")
            daily_g = metrics.daily_summary(m_g, group_cols=["place1"])
            index_g = metrics.mobility_index(daily_g, baseline_days=baseline_days,
                                             group_cols=["place1"])
            index_g_path = out_dir / f"mobility_index_by_place1_r{res}.parquet"
            index_g.to_parquet(index_g_path, index=False)
            print(f"  index by place1: {len(index_g):,} rows -> "
                  f"{index_g_path.name}")

    # ---- quick summary ----------------------------------------------------#
    print("\nsummary:")
    print(f"  stay-at-home rate       : {m['stay_at_home'].mean():.1%}")
    print(f"  median radius of gyration: {m['radius_km'].median():.2f} km")
    print(f"  median trips / day       : {m['n_trips'].median():.0f}")
    print(f"  median cells / day       : {m['n_cells'].median():.0f}")


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
    ap.add_argument("--night-hours", default="22,5",
                    help="'start,end' home-detection night window "
                         "(default '22,5'; 'none' = all hours)")
    ap.add_argument("--baseline-days", default="3",
                    help="baseline = first N distinct dates (int) or a "
                         "comma-separated list of dates, e.g. '2021-10-23,"
                         "2021-10-24' (default '3')")
    ap.add_argument("--people", default=None,
                    help="people-graph parquet to stratify the index by regency")
    args = ap.parse_args()

    mob_path = Path(args.mobility)
    if not mob_path.exists():
        mob_path = config.DEFAULT_MOBILITY_PARQUET
        print(f"note: {args.mobility} not found, using {mob_path}")

    night = None
    if args.night_hours.lower() != "none":
        start, end = (int(x) for x in args.night_hours.split(","))
        night = (start, end)

    baseline = None
    if args.baseline_days.lower() != "none":
        baseline = int(args.baseline_days) if args.baseline_days.isdigit() \
            else [d.strip() for d in args.baseline_days.split(",")]

    build(mob_path, args.res, Path(args.out), args.sample, night_hours=night,
          baseline_days=baseline,
          people_path=Path(args.people) if args.people else None)


if __name__ == "__main__":
    main()

