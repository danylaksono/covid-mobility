"""Compute contact / meeting-index aggregates and cache them to Parquet.

Exposure proxy from device co-location: devices present in the same H3 cell
within the same time bucket are treated as potential "meetings" (see
``src/mobility/contacts.py`` for the rationale and caveats).

Outputs (``<out>``, tagged with resolution and bucket):
- ``contacts_occupancy_r<res>_<bucket>.parquet`` : devices per (bucket, cell)
- ``meeting_index_r<res>_<bucket>.parquet``       : pairwise meetings per bucket
- ``meeting_index_daily_r<res>.parquet``          : meetings per day
- ``crowding_r<res>_<bucket>.parquet``            : #cells with >= k devices

Usage
-----
    python scripts/compute_contacts.py --out data/processed --res 8 --bucket 1h
    python scripts/compute_contacts.py --sample 500000   # quick smoke test
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mobility import config, contacts, io  # noqa: E402


def build(mobility_path: Path, res: int, out_dir: Path, sample: int | None,
          bucket: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    tag = f"r{res}_{bucket}"

    print(f"loading {mobility_path} ...")
    t0 = time.perf_counter()
    df = io.load_mobility(mobility_path)
    if sample:
        df = df.sample(n=sample, random_state=42)
    print(f"  {len(df):,} pings in {time.perf_counter()-t0:.1f}s")

    # ---- occupancy --------------------------------------------------------#
    t0 = time.perf_counter()
    occ = contacts.cell_occupancy(df, res=res, bucket=bucket)
    occ_path = out_dir / f"contacts_occupancy_{tag}.parquet"
    occ.to_parquet(occ_path, index=False)
    print(f"  occupancy: {len(occ):,} (bucket, cell) rows -> {occ_path.name} "
          f"in {time.perf_counter()-t0:.1f}s")

    # ---- meeting indices --------------------------------------------------#
    mi = contacts.meeting_index(occ)
    mi_path = out_dir / f"meeting_index_{tag}.parquet"
    mi.to_parquet(mi_path, index=False)

    mid = contacts.meeting_index_daily(occ)
    mid_path = out_dir / f"meeting_index_daily_{tag}.parquet"
    mid.to_parquet(mid_path, index=False)

    crow = contacts.crowding_counts(occ)
    crow_path = out_dir / f"crowding_{tag}.parquet"
    crow.to_parquet(crow_path, index=False)
    print(f"  indices: {len(mi):,} buckets, {len(mid):,} days, "
          f"{len(crow):,} crowding rows -> {mi_path.name}, "
          f"{mid_path.name}, {crow_path.name}")

    # ---- summary ----------------------------------------------------------#
    print("\nsummary (daily meeting index):")
    print(mid.head().to_string(index=False))


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
    ap.add_argument("--bucket", default="1h",
                    help="co-location time window (pandas offset), e.g. 1h, "
                         "30min, 2h (default 1h)")
    args = ap.parse_args()

    mob_path = Path(args.mobility)
    if not mob_path.exists():
        mob_path = config.DEFAULT_MOBILITY_PARQUET
        print(f"note: {args.mobility} not found, using {mob_path}")

    build(mob_path, args.res, Path(args.out), args.sample, args.bucket)


if __name__ == "__main__":
    main()
