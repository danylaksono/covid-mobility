"""Origin–destination (OD) flow construction.

A simple, well-defined OD model used as input for road-network / trip
analysis and for the OD glyph visualisations:

- Each **device-day** is reduced to an **origin** (first ping's H3 cell) and a
  **destination** (last ping's H3 cell).
- ``device_day_od``      : one row per (maid, date) — the "unit" table.
- ``aggregate_od``       : flows (date, origin, dest) -> n_devices, n_pings.
- ``flow_distance``      : great-circle distance between origin/dest cells.
- ``corridor_change``    : per-OD-pair % change vs a baseline window.
- ``cell_district_map`` / ``label_flows`` / ``aggregate_od_by_place`` :
  district-level OD, using a cell->district map derived from the people graph.
- ``net_flows``          : directional net flow per unordered pair.

All steps are vectorised (H3 + pandas groupby, no per-row Python loops).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import metrics, spatial


def device_day_od(df: pd.DataFrame, res: int) -> pd.DataFrame:
    """Reduce per-device-per-day pings to (origin, destination) H3 cells.

    Parameters
    ----------
    df : cleaned mobility DataFrame with columns ``maid, date, timestamp,
         longitude, latitude``.
    res : H3 resolution for origin/destination cells.

    Returns
    -------
    DataFrame ``[maid, date, origin, dest, n_pings]`` where ``origin``/``dest``
    are h3 cell strings.
    """
    d = df[["maid", "date", "timestamp", "longitude", "latitude"]].copy()
    d["h3"] = spatial.to_h3_cells(d["longitude"].to_numpy(),
                                  d["latitude"].to_numpy(), res)

    # Keep chronological order within each device-day (stable sort).
    d = d.sort_values(["maid", "date", "timestamp"], kind="mergesort")

    grp = d.groupby(["maid", "date"], sort=False, observed=True)
    od = grp.agg(
        origin=("h3", "first"),
        dest=("h3", "last"),
        n_pings=("h3", "size"),
    ).reset_index()
    # origin/dest are already h3 string ids (spatial.to_h3_cells returns strings)
    return od


def aggregate_od(od: pd.DataFrame, *, directed: bool = True) -> pd.DataFrame:
    """Collapse device-day OD rows into flow counts.

    Returns ``[date, origin, dest, n_devices, n_pings]`` for directed flows.
    With ``directed=False``, origin/dest are merged into an unordered pair
    (useful for symmetric flow analysis).
    """
    g = od.copy()
    if not directed:
        pair = g[["origin", "dest"]].apply(
            lambda r: tuple(sorted(r)), axis=1, result_type="expand")
        g["origin"], g["dest"] = pair[0], pair[1]

    out = (g.groupby(["date", "origin", "dest"], observed=True)
             .agg(n_devices=("maid", "nunique"), n_pings=("n_pings", "sum"))
             .reset_index())
    return out


def flow_distance(flows: pd.DataFrame) -> pd.DataFrame:
    """Add ``od_distance_km`` = haversine between origin/dest cell centroids.

    ``flows`` must have ``origin`` / ``dest`` h3 cell strings (no ``res``
    needed — cells are already resolved).
    """
    cells = pd.unique(np.concatenate([
        flows["origin"].to_numpy(), flows["dest"].to_numpy()]))
    lats, lons = spatial.grid_centroids(cells)
    cell_lat = pd.Series(lats, index=cells)
    cell_lon = pd.Series(lons, index=cells)

    out = flows.copy()
    out["od_distance_km"] = metrics.haversine_km(
        out["origin"].map(cell_lon), out["origin"].map(cell_lat),
        out["dest"].map(cell_lon), out["dest"].map(cell_lat))
    return out


def corridor_change(flows: pd.DataFrame, baseline_days: int | list,
                    value_col: str = "n_pings",
                    min_flow: float | None = None) -> pd.DataFrame:
    """Per-OD-pair percent change vs a baseline window (corridor index).

    Parameters
    ----------
    flows : ``aggregate_od`` output (``date, origin, dest, ...``).
    baseline_days : int (first N distinct dates) or list of dates.
    value_col : column to index (e.g. ``n_pings`` or ``n_devices``).
    min_flow : optional; drop corridors whose baseline mean < ``min_flow``.

    Returns
    -------
    ``flows`` plus ``{value_col}_baseline`` and ``{value_col}_pct_change``
    columns and an ``is_baseline`` flag.
    """
    flows = flows.copy()
    dates = pd.to_datetime(flows["date"])
    if isinstance(baseline_days, (int, np.integer)):
        b_dates = dates.drop_duplicates().nsmallest(int(baseline_days))
    else:
        b_dates = pd.to_datetime(list(baseline_days))
    flows["is_baseline"] = dates.isin(b_dates).to_numpy()

    base = (flows[flows["is_baseline"]]
            .groupby(["origin", "dest"], observed=True)[value_col]
            .mean().rename(f"{value_col}_baseline").reset_index())
    out = flows.merge(base, on=["origin", "dest"], how="left")
    if min_flow is not None:
        out = out[out[f"{value_col}_baseline"] >= min_flow]
    out[f"{value_col}_pct_change"] = (
        (out[value_col] - out[f"{value_col}_baseline"])
        / out[f"{value_col}_baseline"] * 100)
    return out


def cell_district_map(homes: pd.DataFrame, people: pd.DataFrame,
                      level: str = "place1") -> dict:
    """Map each home H3 cell -> the majority district of devices homed there.

    Derives a cell -> administrative label map **from the data** (no boundary
    polygons needed): for every home cell, take the most common ``level``
    value among devices whose home is in that cell.

    Parameters
    ----------
    homes : output of ``homes.detect_homes`` (``maid, home_h3, ...``).
    people : cleaned people graph (``maid, place1, place2``).
    level : ``'place1'`` (regency) or ``'place2'`` (district).

    Returns
    -------
    dict ``{home_h3: label}``.
    """
    key = people[["maid", level]].dropna(subset=[level]).drop_duplicates("maid")
    m = homes[["maid", "home_h3"]].merge(key, on="maid", how="inner")
    counts = m.groupby(["home_h3", level], observed=True).size().rename("n").reset_index()
    lab = counts.sort_values("n").drop_duplicates("home_h3", keep="last")
    return dict(zip(lab["home_h3"], lab[level]))


def label_flows(flows: pd.DataFrame, cell_map: dict,
                origin_col: str = "origin", dest_col: str = "dest",
                origin_label: str = "origin_place",
                dest_label: str = "dest_place",
                missing: str = "unknown") -> pd.DataFrame:
    """Map OD h3 cells -> district labels using ``cell_map``."""
    out = flows.copy()
    out[origin_label] = out[origin_col].map(cell_map).fillna(missing)
    out[dest_label] = out[dest_col].map(cell_map).fillna(missing)
    return out


def aggregate_od_by_place(flows: pd.DataFrame,
                          origin_col: str = "origin_place",
                          dest_col: str = "dest_place") -> pd.DataFrame:
    """Sum flows to district level: (date, origin_place, dest_place) -> sums."""
    return (flows.groupby(["date", origin_col, dest_col], observed=True)
            .agg(n_devices=("n_devices", "sum"), n_pings=("n_pings", "sum"))
            .reset_index())


def net_flows(flows: pd.DataFrame, origin_col: str = "origin_place",
              dest_col: str = "dest_place", value_col: str = "n_pings",
              date_col: str = "date") -> pd.DataFrame:
    """Net directional flow per unordered pair, per date.

    ``net = flow(a->b) - flow(b->a)`` for each unordered pair (a < b);
    positive means net movement from a to b.

    Returns ``[date, pair_a, pair_b, net_<value_col>]``.
    """
    rev = flows.rename(columns={origin_col: dest_col, dest_col: origin_col,
                                value_col: "rev"})
    merged = flows.merge(rev, on=[date_col, origin_col, dest_col], how="left")
    merged[f"net_{value_col}"] = merged[value_col].fillna(0) - merged["rev"].fillna(0)
    # keep one row per unordered pair (dedupe by the larger label)
    merged = merged[merged[origin_col] < merged[dest_col]]
    out = merged[[date_col, origin_col, dest_col, f"net_{value_col}"]].rename(
        columns={origin_col: "pair_a", dest_col: "pair_b"})
    return out.reset_index(drop=True)

