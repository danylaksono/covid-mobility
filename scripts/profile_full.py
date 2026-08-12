"""Compute all ``data/processed`` aggregates on the **whole** mobility dataset.

The full 292M-row frame does not fit in RAM (~31.5 GB machine, November alone
peaks near 30 GB), so this script is **memory-bounded by processing the data in
date-chunks**:

1. Partition all dates into chunks of <= ``--chunk-rows`` pings.
2. For each chunk, read just that date range from the combined parquet via
   DuckDB, then reduce it with the existing ``mobility.spatial / od / contacts``
   functions and accumulate the small combined tables in memory.
3. Assemble homes from accumulated night-cell counts, then re-read the chunks
   to compute per-device-day metrics anchored to the *global* homes.
4. Write every ``data/processed/*.parquet`` file with the same names as
   ``scripts/prepare_spatial.py``, ``compute_metrics.py`` and
   ``compute_contacts.py`` (so notebooks/downstream tools are unchanged).

Baselines (``--baseline-days``) are anchored to the first N distinct dates of
the whole study (default: first 3 = 23–25 Oct 2021).

Usage
-----
    python scripts/profile_full.py \
        --mobility data/parquet/mobility.parquet \
        --people  data/parquet/people.parquet \
        --out     data/processed --res 8 --bucket 1h --baseline-days 3

    # smaller / faster smoke test (limit to a date range)
    python scripts/profile_full.py --start-date 2021-10-23 --end-date 2021-11-06
"""

from __future__ import annotations

import argparse
import gc
import sys
import time
from pathlib import Path

import duckdb
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mobility import clean, config, contacts, io, metrics, od, spatial  # noqa: E402


# --------------------------------------------------------------------------- #
# Chunked loading
# --------------------------------------------------------------------------- #

def _unix(d) -> int:
    """Unix seconds for a UTC date (datetime.date / pandas Timestamp)."""
    return int(pd.Timestamp(d).value // 1_000_000_000)


def _build_chunks(mob_path: Path, target_rows: int,
                  start_date=None, end_date=None) -> list[list[pd.Timestamp]]:
    """Group all dates into chunks each with <= ``target_rows`` pings."""
    con = duckdb.connect()
    try:
        conds = []
        if start_date is not None:
            conds.append(f"timestamp >= {_unix(start_date)}")
        if end_date is not None:
            conds.append(f"timestamp < {_unix(pd.Timestamp(end_date) + pd.Timedelta(days=1))}")
        where = (" WHERE " + " AND ".join(conds)) if conds else ""
        sql = ("SELECT CAST(to_timestamp(timestamp) AS DATE) AS d, count(*) AS n "
               "FROM read_parquet(?)" + where + " GROUP BY 1 ORDER BY 1")
        rows = con.execute(sql, [str(mob_path)]).fetchall()
    finally:
        con.close()
    if not rows:
        raise SystemExit("no data in the requested date range")

    chunks, cur, cur_n = [], [], 0
    for d, n in rows:
        cur.append(pd.Timestamp(d))
        cur_n += n
        if cur_n >= target_rows:
            chunks.append(cur)
            cur, cur_n = [], 0
    if cur:
        chunks.append(cur)
    return chunks


def _load_chunk(mob_path: Path, dates: list[pd.Timestamp]) -> pd.DataFrame:
    """Read one date chunk from the combined parquet (DuckDB) + clean it."""
    t0, t1 = _unix(dates[0]), _unix(dates[-1] + pd.Timedelta(days=1))
    con = duckdb.connect()
    try:
        df = con.execute(
            "SELECT maid, latitude, longitude, timestamp "
            "FROM read_parquet(?) WHERE timestamp >= ? AND timestamp < ?",
            [str(mob_path), t0, t1]).df()
    finally:
        con.close()
    return clean.clean_mobility(df)  # adds datetime / date / hour


def _night_counts(df: pd.DataFrame, res: int,
                  night_hours: tuple[int, int]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(maid, h3, n) night-ping counts + per-maid distinct nights for a chunk."""
    d = df[["maid", "date", "hour", "longitude", "latitude"]].copy()
    d = d.dropna(subset=["longitude", "latitude"])
    start, end = night_hours
    if start <= end:
        d = d[d["hour"].between(start, end)]
    else:  # wraps midnight, e.g. 22–05
        d = d[(d["hour"] >= start) | (d["hour"] <= end)]
    if d.empty:
        empty_c = pd.DataFrame(columns=["maid", "h3", "n"])
        empty_n = pd.DataFrame(columns=["maid", "n_nights"])
        return empty_c, empty_n
    d["h3"] = spatial.to_h3_cells(d["longitude"].to_numpy(),
                                  d["latitude"].to_numpy(), res)
    nc = d.groupby(["maid", "h3"], sort=False).size().rename("n").reset_index()
    nn = d.groupby("maid")["date"].nunique().rename("n_nights").reset_index()
    return nc, nn


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def build(mob_path: Path, res: int, out_dir: Path, bucket: str,
          night_hours: tuple[int, int], baseline_days: int | list,
          people_path: Path | None, chunk_rows: int,
          start_date=None, end_date=None) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    tag = f"r{res}_{bucket}"
    t_start = time.perf_counter()

    print(f"partitioning dates (chunk target ~{chunk_rows:,} rows) ...", flush=True)
    chunks = _build_chunks(mob_path, chunk_rows, start_date, end_date)
    total_days = sum(len(c) for c in chunks)
    print(f"  {len(chunks)} chunks over {total_days} days", flush=True)

    # ---- pass 1: grid, OD, occupancy, night counts ------------------------#
    grid_parts, od_parts, occ_parts = [], [], []
    mi_parts, mid_parts, crow_parts = [], [], []
    nc_parts, nn_parts = [], []
    for i, dates in enumerate(chunks, 1):
        t0 = time.perf_counter()
        df = _load_chunk(mob_path, dates)
        print(f"[pass1 {i}/{len(chunks)}] {dates[0].date()}..{dates[-1].date()} "
              f"{len(df):,} pings loaded in {time.perf_counter()-t0:.1f}s", flush=True)

        grid_parts.append(spatial.aggregate_grid(df, res=res, time_bucket="date"))
        od_parts.append(od.device_day_od(df, res=res))
        occ = contacts.cell_occupancy(df, res=res, bucket=bucket)
        occ_parts.append(occ)
        mi_parts.append(contacts.meeting_index(occ))
        mid_parts.append(contacts.meeting_index_daily(occ))
        crow_parts.append(contacts.crowding_counts(occ))
        nc, nn = _night_counts(df, res, night_hours)
        nc_parts.append(nc)
        nn_parts.append(nn)

        del df, occ, nc, nn
        gc.collect()

    # ---- homes (global) ---------------------------------------------------#
    t0 = time.perf_counter()
    nc_all = pd.concat(nc_parts, ignore_index=True)
    nc_all = nc_all.groupby(["maid", "h3"], sort=False)["n"].sum().reset_index()
    homes = nc_all.sort_values("n").drop_duplicates("maid", keep="last")
    homes = homes.rename(columns={"h3": "home_h3", "n": "n_home_pings"})
    nn_all = pd.concat(nn_parts, ignore_index=True)
    nn_all = nn_all.groupby("maid", sort=False)["n_nights"].sum().reset_index()
    homes = homes.merge(nn_all, on="maid", how="left").fillna({"n_nights": 0})
    lats, lons = spatial.grid_centroids(homes["home_h3"])
    homes["home_lat"], homes["home_lon"] = lats, lons
    homes_path = out_dir / f"homes_r{res}.parquet"
    homes.to_parquet(homes_path, index=False)
    print(f"  homes: {len(homes):,} devices -> {homes_path.name} "
          f"in {time.perf_counter()-t0:.1f}s", flush=True)
    del nc_all, nn_all, nc_parts, nn_parts
    gc.collect()

    # ---- spatial: grid + concentration ------------------------------------#
    t0 = time.perf_counter()
    grid = pd.concat(grid_parts, ignore_index=True)
    grid = grid.groupby(["date", "h3"], sort=True)["count"].sum().reset_index()
    grid_path = out_dir / f"h3_grid_r{res}_daily.parquet"
    grid.to_parquet(grid_path, index=False)
    conc = spatial.concentration(grid, value_col="count", group_cols=["date"])
    conc_path = out_dir / f"concentration_r{res}.parquet"
    conc.to_parquet(conc_path, index=False)
    print(f"  h3 grid {len(grid):,} rows, concentration {len(conc):,} days "
          f"in {time.perf_counter()-t0:.1f}s", flush=True)
    del grid_parts
    gc.collect()

    # ---- OD: device-day -> flows -> corridor / district -------------------#
    t0 = time.perf_counter()
    od_all = pd.concat(od_parts, ignore_index=True)
    od_path = out_dir / f"od_device_day_r{res}.parquet"
    od_all.to_parquet(od_path, index=False)
    flows = od.flow_distance(od.aggregate_od(od_all))
    flows_path = out_dir / f"od_flows_r{res}.parquet"
    flows.to_parquet(flows_path, index=False)
    print(f"  OD: {len(od_all):,} device-days, {len(flows):,} flows in "
          f"{time.perf_counter()-t0:.1f}s", flush=True)
    del od_parts
    gc.collect()

    if baseline_days is not None:
        t0 = time.perf_counter()
        corr = od.corridor_change(flows, baseline_days=baseline_days)
        corr_path = out_dir / f"od_corridor_change_r{res}.parquet"
        corr.to_parquet(corr_path, index=False)
        print(f"  corridor change: {len(corr):,} rows -> {corr_path.name} "
              f"in {time.perf_counter()-t0:.1f}s", flush=True)

    if people_path is not None and people_path.exists():
        t0 = time.perf_counter()
        people = io.load_people(people_path)
        level = "place1"
        cell_map = od.cell_district_map(homes, people, level=level)
        labeled = od.label_flows(flows, cell_map,
                                 origin_label=f"origin_{level}",
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
              f"{len(net):,} net pairs in {time.perf_counter()-t0:.1f}s",
              flush=True)

    # ---- pass 2: metrics anchored to global homes -------------------------#
    metric_parts = []
    for i, dates in enumerate(chunks, 1):
        t0 = time.perf_counter()
        df = _load_chunk(mob_path, dates)
        m = metrics.device_day_metrics(df, res=res, homes=homes)
        metric_parts.append(m)
        print(f"[pass2 {i}/{len(chunks)}] {dates[0].date()}..{dates[-1].date()} "
              f"{len(m):,} device-days in {time.perf_counter()-t0:.1f}s",
              flush=True)
        del df, m
        gc.collect()

    t0 = time.perf_counter()
    metrics_all = pd.concat(metric_parts, ignore_index=True)
    metrics_path = out_dir / f"metrics_device_day_r{res}.parquet"
    metrics_all.to_parquet(metrics_path, index=False)
    print(f"  metrics: {len(metrics_all):,} device-days -> {metrics_path.name} "
          f"in {time.perf_counter()-t0:.1f}s", flush=True)

    if baseline_days is not None:
        daily = metrics.daily_summary(metrics_all)
        index = metrics.mobility_index(daily, baseline_days=baseline_days)
        index_path = out_dir / f"mobility_index_r{res}.parquet"
        index.to_parquet(index_path, index=False)
        print(f"  mobility index: {len(index):,} days -> {index_path.name}",
              flush=True)

        if people_path is not None and people_path.exists():
            prof = people[["maid", "place1"]].drop_duplicates("maid")
            m_g = metrics_all.merge(prof, on="maid", how="left")
            daily_g = metrics.daily_summary(m_g, group_cols=["place1"])
            index_g = metrics.mobility_index(daily_g, baseline_days=baseline_days,
                                             group_cols=["place1"])
            index_g_path = out_dir / f"mobility_index_by_place1_r{res}.parquet"
            index_g.to_parquet(index_g_path, index=False)
            print(f"  index by place1: {len(index_g):,} rows -> {index_g_path.name}",
                  flush=True)
    del metric_parts
    gc.collect()

    # ---- contacts: occupancy + meeting indices ----------------------------#
    t0 = time.perf_counter()
    occ_all = pd.concat(occ_parts, ignore_index=True)
    occ_path = out_dir / f"contacts_occupancy_{tag}.parquet"
    occ_all.to_parquet(occ_path, index=False)
    mi = contacts.meeting_index(occ_all)
    mi.to_parquet(out_dir / f"meeting_index_{tag}.parquet", index=False)
    mid = contacts.meeting_index_daily(occ_all)
    mid.to_parquet(out_dir / f"meeting_index_daily_{tag}.parquet", index=False)
    crow = contacts.crowding_counts(occ_all)
    crow.to_parquet(out_dir / f"crowding_{tag}.parquet", index=False)
    print(f"  contacts: {len(occ_all):,} (bucket, cell) rows, {len(mi):,} "
          f"buckets, {len(mid):,} days, {len(crow):,} crowding rows in "
          f"{time.perf_counter()-t0:.1f}s", flush=True)

    # ---- summary ----------------------------------------------------------#
    print("\nsummary:", flush=True)
    print(f"  total pings           : {grid['count'].sum():,}", flush=True)
    print(f"  distinct days         : {grid['date'].nunique():,}", flush=True)
    print(f"  distinct devices      : {homes['maid'].nunique():,}", flush=True)
    print(f"  device-days           : {len(od_all):,}", flush=True)
    print(f"  stay-at-home rate     : {metrics_all['stay_at_home'].mean():.1%}", flush=True)
    print(f"  median radius (km)    : {metrics_all['radius_km'].median():.2f}", flush=True)
    print(f"  median trips / day    : {metrics_all['n_trips'].median():.0f}", flush=True)
    print(f"  median cells / day    : {metrics_all['n_cells'].median():.0f}", flush=True)
    print(f"\nALL DONE in {(time.perf_counter()-t_start)/60:.1f} min", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mobility", default=str(config.MOBILITY_PARQUET),
                    help="cleaned mobility parquet "
                         f"(default: {config.MOBILITY_PARQUET})")
    ap.add_argument("--res", type=int, default=config.H3_RES_GRID)
    ap.add_argument("--out", default=str(config.PROCESSED_DIR))
    ap.add_argument("--bucket", default="1h",
                    help="contact co-location time window (default 1h)")
    ap.add_argument("--night-hours", default="22,5",
                    help="'start,end' home-detection night window (default '22,5')")
    ap.add_argument("--baseline-days", default="3",
                    help="baseline = first N distinct dates or date list "
                         "(default 3; 'none' to skip)")
    ap.add_argument("--people", default=None,
                    help="people-graph parquet for district OD / by-place1 index")
    ap.add_argument("--chunk-rows", type=int, default=30_000_000,
                    help="max pings per date chunk (memory bound, default 30M)")
    ap.add_argument("--start-date", default=None, help="optional date limit (YYYY-MM-DD)")
    ap.add_argument("--end-date", default=None, help="optional date limit (YYYY-MM-DD)")
    args = ap.parse_args()

    baseline = None
    if args.baseline_days.lower() != "none":
        baseline = int(args.baseline_days) if args.baseline_days.isdigit() \
            else [d.strip() for d in args.baseline_days.split(",")]

    night = None
    if args.night_hours.lower() != "none":
        start, end = (int(x) for x in args.night_hours.split(","))
        night = (start, end)

    people_path = Path(args.people) if args.people else None
    if people_path is not None and not people_path.exists():
        people_path = config.PEOPLE_PARQUET if config.PEOPLE_PARQUET.exists() else None

    build(Path(args.mobility), args.res, Path(args.out), args.bucket, night,
          baseline, people_path, args.chunk_rows,
          args.start_date, args.end_date)


if __name__ == "__main__":
    main()
