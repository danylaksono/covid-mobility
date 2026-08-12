"""People-dependent aggregates for the full-data profile (supplement).

``profile_full.py`` skips district-level OD and the by-place1 mobility index
when no ``--people`` is passed. Run this *after* ``profile_full.py`` to compute
those three tables from the already-written combined outputs (``od_flows_*``,
``homes_*``, ``metrics_device_day_*``) plus the people graph:

- ``od_flows_district_r<res>.parquet``
- ``od_net_flows_district_r<res>.parquet``
- ``mobility_index_by_place1_r<res>.parquet``

Usage
-----
    python scripts/profile_full_people.py --out data/processed --res 8 \
        --people data/parquet/people.parquet --baseline-days 3
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mobility import config, io, metrics, od  # noqa: E402


def build(out_dir: Path, res: int, people_path: str | Path,
          baseline_days: int | list) -> None:
    tag = f"r{res}"
    people = io.load_people(people_path)

    # ---- district-level OD (place1) --------------------------------------#
    t0 = time.perf_counter()
    flows = pd.read_parquet(out_dir / f"od_flows_{tag}.parquet")
    homes = pd.read_parquet(out_dir / f"homes_{tag}.parquet")
    cell_map = od.cell_district_map(homes, people, level="place1")
    labeled = od.label_flows(flows, cell_map, origin_label="origin_place1",
                             dest_label="dest_place1")
    dist = od.aggregate_od_by_place(labeled, origin_col="origin_place1",
                                    dest_col="dest_place1")
    dist_path = out_dir / f"od_flows_district_{tag}.parquet"
    dist.to_parquet(dist_path, index=False)
    net = od.net_flows(dist, origin_col="origin_place1", dest_col="dest_place1")
    net_path = out_dir / f"od_net_flows_district_{tag}.parquet"
    net.to_parquet(net_path, index=False)
    print(f"district OD (place1): {len(dist):,} flows, {len(net):,} net pairs "
          f"-> {dist_path.name}, {net_path.name} in {time.perf_counter()-t0:.1f}s")

    # ---- mobility index stratified by regency (place1) -------------------#
    t0 = time.perf_counter()
    m = pd.read_parquet(out_dir / f"metrics_device_day_{tag}.parquet")
    key = people[["maid", "place1"]].drop_duplicates("maid")
    m_g = m.merge(key, on="maid", how="left")
    daily_g = metrics.daily_summary(m_g, group_cols=["place1"])
    index_g = metrics.mobility_index(daily_g, baseline_days=baseline_days,
                                     group_cols=["place1"])
    index_g_path = out_dir / f"mobility_index_by_place1_{tag}.parquet"
    index_g.to_parquet(index_g_path, index=False)
    print(f"index by place1: {len(index_g):,} rows -> {index_g_path.name} "
          f"in {time.perf_counter()-t0:.1f}s")


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(config.PROCESSED_DIR))
    ap.add_argument("--res", type=int, default=config.H3_RES_GRID)
    ap.add_argument("--people", default=str(config.PEOPLE_PARQUET))
    ap.add_argument("--baseline-days", default="3",
                    help="baseline = first N distinct dates or date list (default 3)")
    args = ap.parse_args()

    baseline = (int(args.baseline_days) if args.baseline_days.isdigit()
                else [d.strip() for d in args.baseline_days.split(",")])

    build(Path(args.out), args.res, args.people, baseline)


if __name__ == "__main__":
    main()
