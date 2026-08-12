"""Contact / meeting index — an exposure proxy from device co-location.

Rationale
---------
Without contact-tracing data, a standard mobility-based proxy for potential
COVID exposure is **co-location**: devices present in the same H3 cell within
the same short time window are treated as a potential "meeting". This mirrors
Google's "meeting index" / density-based exposure measures.

Metrics (all vectorised)
------------------------
- ``cell_occupancy``      : distinct devices (and pings) per (time bucket, cell).
- ``meeting_index``       : per bucket, sum over cells of pairwise co-locations
                            C(n, 2) = n*(n-1)/2 (devices sharing a cell+bucket).
- ``meeting_index_daily`` : same, aggregated to whole days.
- ``crowding_counts``     : per bucket, number of cells with >= k devices
                            (for k in ``thresholds``), i.e. "crowded" locations.

Caveats
-------
- A "meeting" is a *presence overlap*, not necessarily physical contact; treat
  the index as a relative trend measure, not an absolute contact count.
- H3 resolution and bucket size control sensitivity: r8 (~0.66 km) + 1 h is a
  sensible default; smaller cells / shorter buckets = stricter definition.
"""

from __future__ import annotations

import pandas as pd

from . import spatial


def cell_occupancy(df: pd.DataFrame, res: int,
                   time_col: str = "datetime", bucket: str = "1h") -> pd.DataFrame:
    """Distinct devices and pings per (time bucket, H3 cell).

    Parameters
    ----------
    df : cleaned mobility frame with ``maid, <time_col>, longitude, latitude``.
    res : H3 resolution for the co-location cell.
    bucket : pandas offset string for the time window, e.g. ``"1h"``, ``"30min"``.

    Returns
    -------
    DataFrame ``[bucket, h3, n_devices, n_pings]`` (only cells that had pings).
    """
    d = df[["maid", time_col, "longitude", "latitude"]].copy()
    d = d.dropna(subset=["longitude", "latitude"])
    if d.empty:
        return pd.DataFrame(columns=["bucket", "h3", "n_devices", "n_pings"])

    d["h3"] = spatial.to_h3_cells(d["longitude"].to_numpy(),
                                  d["latitude"].to_numpy(), res)
    d["bucket"] = pd.to_datetime(d[time_col]).dt.floor(bucket)

    occ = (d.groupby(["bucket", "h3"], observed=True)
           .agg(n_devices=("maid", "nunique"), n_pings=("maid", "size"))
           .reset_index())
    return occ


def meeting_index(occupancy: pd.DataFrame, min_devices: int = 2) -> pd.DataFrame:
    """Pairwise co-location ("meetings") per time bucket.

    For each (bucket, cell) with ``n_devices >= min_devices``, count
    ``n*(n-1)/2`` potential pairwise contacts; sum them per bucket.
    """
    occ = occupancy[occupancy["n_devices"] >= min_devices].copy()
    occ["meetings"] = occ["n_devices"] * (occ["n_devices"] - 1) / 2
    return (occ.groupby("bucket")["meetings"].sum()
            .rename("meeting_index").reset_index())


def meeting_index_daily(occupancy: pd.DataFrame, min_devices: int = 2) -> pd.DataFrame:
    """Same as :func:`meeting_index` but aggregated to whole days."""
    occ = occupancy[occupancy["n_devices"] >= min_devices].copy()
    occ["meetings"] = occ["n_devices"] * (occ["n_devices"] - 1) / 2
    occ["date"] = pd.to_datetime(occ["bucket"]).dt.normalize()
    return (occ.groupby("date")["meetings"].sum()
            .rename("meeting_index").reset_index())


def crowding_counts(occupancy: pd.DataFrame,
                    thresholds: tuple[int, ...] = (2, 5, 10, 20)) -> pd.DataFrame:
    """Per time bucket, the number of cells with >= k devices, for each k.

    Returns ``[bucket, cells_n2, cells_n5, cells_n10, cells_n20]``.
    """
    occ = occupancy.copy()
    occ["bucket"] = pd.to_datetime(occ["bucket"])
    cols = {}
    for k in thresholds:
        cols[f"cells_n{k}"] = occ[occ["n_devices"] >= k].groupby("bucket").size()
    out = pd.DataFrame(cols).fillna(0).reset_index()
    return out
