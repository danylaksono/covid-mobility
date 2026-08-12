"""Reusable exploration toolkit for the UGM mobility datasets.

Thin CLI on top of the ``mobility`` package (src/mobility). Prints an overview
of any mobility/people dataset — use it to sanity-check new data before
analysing it. All cleaning is delegated to ``mobility.clean``.

Usage
-----
    python scripts/explore_data.py                     # default datasets
    python scripts/explore_data.py --mobility <path> \
                                   --people <path>     # any new files
    python scripts/explore_data.py --quick             # head-only, faster
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd  # noqa: E402

from mobility import clean, config, io  # noqa: E402

# --------------------------------------------------------------------------- #
# Summaries
# --------------------------------------------------------------------------- #

def overview_mobility(gdf) -> None:
    print("=" * 70)
    print("MOBILITY OVERVIEW")
    print("=" * 70)
    print(f"records        : {len(gdf):,}")
    print(f"unique devices : {gdf['maid'].nunique():,}")
    print(f"date range     : {gdf['datetime'].min()}  ->  {gdf['datetime'].max()}")
    if "longitude" in gdf.columns and "latitude" in gdf.columns:
        print(f"spatial extent : lon {gdf['longitude'].min():.3f}-{gdf['longitude'].max():.3f}, "
              f"lat {gdf['latitude'].min():.3f}-{gdf['latitude'].max():.3f}")
    print("\ncolumns / dtypes:")
    print(gdf.dtypes.to_string())
    print("\nsample:")
    print(gdf[["maid", "latitude", "longitude", "datetime"]].head().to_string())
    print("\ndaily pings & active devices:")
    daily = gdf.groupby("date").agg(
        pings=("maid", "size"), devices=("maid", "nunique"))
    print(daily.to_string())


def overview_people(df: pd.DataFrame) -> None:
    print("=" * 70)
    print("PEOPLE-GRAPH OVERVIEW")
    print("=" * 70)
    p = clean.profiles(df)
    print(f"rows            : {len(df):,}")
    print(f"unique devices  : {len(p):,}")
    print("\ncolumns / dtypes:")
    print(df.dtypes.to_string())
    for col in ["sex", "intensity", "country", "province", "place1"]:
        if col in df.columns:
            print(f"\n{col} (per device):")
            print(p[col].value_counts(dropna=True).to_string())
    if {"place1", "intensity"}.issubset(df.columns):
        print("\nintensity x place1 (per device):")
        print(pd.crosstab(p["place1"], p["intensity"]).to_string())


def overview(gdf, df: pd.DataFrame) -> None:
    overview_mobility(gdf)
    overview_people(df)
    inter = set(gdf["maid"].unique()) & set(df["maid"].unique())
    print("=" * 70)
    print(f"overlap mobility <-> people : {len(inter):,} devices "
          f"({len(inter) / gdf['maid'].nunique():.1%} of mobility devices)")
    print("=" * 70)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main() -> None:
    ap = argparse.ArgumentParser(description="Explore UGM mobility datasets.")
    ap.add_argument("--mobility", default=str(config.DEFAULT_MOBILITY_PARQUET))
    ap.add_argument("--people", default=str(config.DEFAULT_PEOPLE_PARQUET))
    ap.add_argument("--quick", action="store_true",
                    help="read only 200k rows for a fast look")
    args = ap.parse_args()

    print(f"loading mobility from {args.mobility} ...")
    mob = io.load_mobility(args.mobility)
    if args.quick:
        mob = mob.head(200_000)
    print(f"loading people from   {args.people} ...")
    pp = io.load_people(args.people)
    if args.quick:
        pp = pp.head(200_000)
    overview(mob, pp)


if __name__ == "__main__":
    main()
