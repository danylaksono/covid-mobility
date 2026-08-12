"""Per-device-per-day mobility metrics.

These are the building blocks for the COVID mobility analysis and for the
glyph-based visualisations:

- ``n_pings``          : activity volume
- ``n_cells``          : distinct H3 cells visited (visited-location count)
- ``n_trips``          : number of H3-cell transitions (moves between pings)
- ``radius_km``        : radius of gyration (RMS distance from the daily centroid)
- ``max_dist_home_km`` : farthest distance from the home cell (needs ``homes``)
- ``stay_at_home``     : True if every ping falls in the home cell

All reductions are vectorised (groupby over (maid, date) — no per-group loops),
so the full 12M-row dataset runs in seconds.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import spatial


def haversine_km(lon1, lat1, lon2, lat2) -> np.ndarray:
    """Haversine great-circle distance in km (vectorised on arrays)."""
    R = 6371.0
    lon1, lat1, lon2, lat2 = map(np.radians, [lon1, lat1, lon2, lat2])
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 2 * R * np.arcsin(np.sqrt(a))


def device_day_metrics(df: pd.DataFrame, res: int,
                       homes: pd.DataFrame | None = None) -> pd.DataFrame:
    """Compute per (``maid``, ``date``) mobility metrics.

    Parameters
    ----------
    df : cleaned mobility frame with ``maid, date, timestamp, longitude,
         latitude``.
    res : H3 resolution for cells / trip counting.
    homes : optional output of ``homes.detect_homes`` (columns ``maid,
        home_h3, home_lon, home_lat``). When provided, ``max_dist_home_km``
        and ``stay_at_home`` are computed against it.

    Returns
    -------
    DataFrame ``[maid, date, n_pings, n_cells, n_trips, radius_km,
                 max_dist_home_km, stay_at_home]``.
    """
    cols = ["maid", "date", "timestamp", "longitude", "latitude"]
    d = df[cols].dropna(subset=["longitude", "latitude"]).copy()
    if d.empty:
        return pd.DataFrame(columns=cols + ["n_pings", "n_cells", "n_trips",
                                            "radius_km", "max_dist_home_km",
                                            "stay_at_home"])

    d["h3"] = spatial.to_h3_cells(d["longitude"].to_numpy(),
                                  d["latitude"].to_numpy(), res)
    d = d.sort_values(["maid", "date", "timestamp"], kind="mergesort")

    # --- trips: number of H3-cell transitions between consecutive pings ---
    prev = d.groupby(["maid", "date"], sort=False)["h3"].shift(1)
    d["move"] = (d["h3"] != prev).fillna(False)

    # --- radius of gyration: RMS distance from the daily centroid ---
    g = d.groupby(["maid", "date"], sort=False)
    d["c_lon"] = g["longitude"].transform("mean")
    d["c_lat"] = g["latitude"].transform("mean")
    d["sq_km"] = haversine_km(d["longitude"], d["latitude"],
                              d["c_lon"], d["c_lat"]) ** 2

    agg = d.groupby(["maid", "date"], sort=False).agg(
        n_pings=("h3", "size"),
        n_cells=("h3", "nunique"),
        n_trips=("move", "sum"),
        sq_sum=("sq_km", "sum"),
    )
    agg["radius_km"] = np.sqrt(agg["sq_sum"] / agg["n_pings"])
    agg = agg.drop(columns="sq_sum")

    # --- home-anchored metrics (optional) ---
    agg["max_dist_home_km"] = np.nan
    agg["stay_at_home"] = np.nan
    if homes is not None and len(homes):
        h = homes[["maid", "home_h3", "home_lon", "home_lat"]]
        dd = d.merge(h, on="maid", how="left")
        dd["dist_home_km"] = haversine_km(dd["longitude"], dd["latitude"],
                                          dd["home_lon"], dd["home_lat"])
        dd["in_home"] = dd["h3"] == dd["home_h3"]

        g2 = dd.groupby(["maid", "date"], sort=False)
        agg["max_dist_home_km"] = g2["dist_home_km"].max()
        n_all = g2["h3"].size()
        n_in_home = g2["in_home"].sum()
        agg["stay_at_home"] = (n_in_home == n_all)

    return agg.reset_index()


# --------------------------------------------------------------------------- #
# Aggregates & baseline index (Google / Apple mobility-report style)
# --------------------------------------------------------------------------- #

def daily_summary(metrics_df: pd.DataFrame,
                  group_cols: list[str] | None = None) -> pd.DataFrame:
    """Aggregate per-device-day metrics into a per-day (x group) summary.

    Parameters
    ----------
    metrics_df : output of :func:`device_day_metrics` (columns ``maid, date,
        n_pings, n_cells, n_trips, radius_km, max_dist_home_km, stay_at_home``).
    group_cols : optional stratification columns present in ``metrics_df``
        (e.g. ``place1`` after joining the people graph).

    Returns
    -------
    DataFrame with ``date``, optional group cols, and
    ``n_devices, n_device_days, n_pings, n_trips, pings_per_device_day,
    radius_km, n_cells, max_dist_home_km, stay_at_home``.
    """
    keys = ["date"] + list(group_cols or [])
    g = metrics_df.groupby(keys, sort=True, observed=True)
    out = g.agg(
        n_devices=("maid", "nunique"),
        n_device_days=("maid", "size"),
        n_pings=("n_pings", "sum"),
        n_trips=("n_trips", "sum"),
        radius_km=("radius_km", "mean"),
        n_cells=("n_cells", "mean"),
        max_dist_home_km=("max_dist_home_km", "mean"),
        stay_at_home=("stay_at_home", "mean"),
    )
    out["pings_per_device_day"] = out["n_pings"] / out["n_device_days"]
    return out.reset_index()


def mobility_index(daily: pd.DataFrame, baseline_days: int | list,
                   value_cols: list[str] | None = None,
                   group_cols: list[str] | None = None) -> pd.DataFrame:
    """Google/Apple-style daily index: per-day value + % change vs baseline.

    Parameters
    ----------
    daily : output of :func:`daily_summary` (or anything with a ``date`` col).
    baseline_days : int (use the first N distinct dates) or list of date
        strings / Timestamps.
    value_cols : columns to index; default = all numeric non-key columns.
    group_cols : optional stratification columns present in ``daily``.

    Returns
    -------
    ``daily`` plus, for each indexed column ``c``, a ``{c}_baseline`` column
    and a ``{c}_pct_change`` column (percent change vs the baseline mean),
    plus an ``is_baseline`` flag.
    """
    daily = daily.copy()
    dates = pd.to_datetime(daily["date"])

    if isinstance(baseline_days, (int, np.integer)):
        b_dates = dates.drop_duplicates().nsmallest(int(baseline_days))
    else:
        b_dates = pd.to_datetime(list(baseline_days))
    is_base = dates.isin(b_dates).to_numpy()

    group_cols = list(group_cols or [])
    if value_cols is None:
        value_cols = [c for c in daily.columns
                      if c not in ["date", *group_cols]
                      and pd.api.types.is_numeric_dtype(daily[c])]

    out = daily.copy()
    if group_cols:
        base = (daily[is_base].groupby(group_cols, observed=True)[value_cols]
                .mean().reset_index())
        out = out.merge(base, on=group_cols, how="left", suffixes=("", "_baseline"))
    else:
        base_mean = daily[is_base][value_cols].mean()
        for c in value_cols:
            out[f"{c}_baseline"] = base_mean[c]

    for c in value_cols:
        out[f"{c}_pct_change"] = (out[c] - out[f"{c}_baseline"]) / out[f"{c}_baseline"] * 100
    out["is_baseline"] = is_base
    return out
