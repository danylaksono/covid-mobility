"""Run the full mobility pipeline end-to-end for the current data.

Steps (in dependency order), each reusing the individual scripts' logic:

    1. process_mobility   : raw CSVs -> cleaned parquet (data/parquet)
    2. prepare_spatial    : H3 grids, concentration, OD (+ corridor, district)
    3. compute_metrics    : homes, per-device-day metrics, baseline index
    4. compute_contacts   : co-location / meeting index

Run from the repo root:

    python scripts/run_all.py                          # full data
    python scripts/run_all.py --sample 500000          # quick smoke test
    python scripts/run_all.py --no-people --no-plot    # skip optional extras
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))  # sibling scripts

from mobility import config  # noqa: E402

import process_mobility  # noqa: E402
import prepare_spatial  # noqa: E402
import compute_metrics  # noqa: E402
import compute_contacts  # noqa: E402


def banner(step: str) -> None:
    print("\n" + "=" * 72)
    print(f"STEP: {step}")
    print("=" * 72)


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw-dir", default=str(config.RAW_DIR),
                    help="data/raw dir to ingest (recursive, month-grouped; "
                         "default data/raw)")
    ap.add_argument("--people-csv", default="data/raw/people_graph.csv",
                    help="people-graph CSV (default data/raw/people_graph.csv)")
    ap.add_argument("--out", default=str(config.PROCESSED_DIR))
    ap.add_argument("--res", type=int, default=config.H3_RES_GRID)
    ap.add_argument("--sample", type=int, default=None,
                    help="random sample size (for quick tests)")
    ap.add_argument("--bucket", default="1h",
                    help="contact co-location window (default 1h)")
    ap.add_argument("--baseline-days", default="3",
                    help="baseline = first N distinct dates or date list "
                         "(default 3; 'none' to skip)")
    ap.add_argument("--night-hours", default="22,5",
                    help="'start,end' home-detection night window")
    ap.add_argument("--plot", default=None, nargs="?", const="outputs/maps",
                    help="dir for static map PNGs (optional)")
    ap.add_argument("--no-people", action="store_true",
                    help="skip district-level OD / by-place1 index")
    args = ap.parse_args()

    out_dir = Path(args.out)
    parquet_dir = config.PARQUET_DIR

    baseline = None
    if args.baseline_days.lower() != "none":
        baseline = int(args.baseline_days) if args.baseline_days.isdigit() \
            else [d.strip() for d in args.baseline_days.split(",")]

    night = None
    if args.night_hours.lower() != "none":
        start, end = (int(x) for x in args.night_hours.split(","))
        night = (start, end)

    plot_dir = Path(args.plot) if args.plot else None
    people_parquet = None if args.no_people else config.PEOPLE_PARQUET

    # ---- 1. ingest --------------------------------------------------------#
    banner("1/4 process_mobility: raw CSVs -> parquet")
    t0 = time.perf_counter()
    process_mobility.convert_mobility_tree(args.raw_dir, parquet_dir)
    if Path(args.people_csv).exists():
        process_mobility.convert_people(args.people_csv, parquet_dir)
    print(f"  ingest done in {time.perf_counter()-t0:.1f}s")

    # ---- 2. spatial -------------------------------------------------------#
    banner("2/4 prepare_spatial: H3 grids, concentration, OD")
    t0 = time.perf_counter()
    prepare_spatial.build(config.MOBILITY_PARQUET, args.res, out_dir,
                          args.sample, plot_dir, baseline_days=baseline,
                          people_path=people_parquet, level="place1")
    print(f"  spatial done in {time.perf_counter()-t0:.1f}s")

    # ---- 3. metrics -------------------------------------------------------#
    banner("3/4 compute_metrics: homes + device-day metrics + index")
    t0 = time.perf_counter()
    compute_metrics.build(config.MOBILITY_PARQUET, args.res, out_dir,
                          args.sample, night_hours=night,
                          baseline_days=baseline, people_path=people_parquet)
    print(f"  metrics done in {time.perf_counter()-t0:.1f}s")

    # ---- 4. contacts ------------------------------------------------------#
    banner("4/4 compute_contacts: meeting index + crowding")
    t0 = time.perf_counter()
    compute_contacts.build(config.MOBILITY_PARQUET, args.res, out_dir,
                           args.sample, args.bucket)
    print(f"  contacts done in {time.perf_counter()-t0:.1f}s")

    banner("ALL STEPS COMPLETE")
    print(f"outputs in {out_dir.resolve()}")


if __name__ == "__main__":
    main()
