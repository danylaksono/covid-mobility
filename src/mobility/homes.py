"""Home-location detection.

A device's "home" is its **most frequent H3 cell during a baseline window**
(default: night hours across all available days). Returns one row per device
with the home cell + centroid, ready to join back to pings or metrics.

Design notes
------------
- Vectorised: H3 cells are assigned with ``spatial.to_h3_cells``, then a
  ``(maid, cell)`` count and a single "most frequent cell per maid" reduction
  (no per-device Python loops).
- Output is cached to Parquet (``data/processed/homes.parquet``) so it is
  computed once.
"""

from __future__ import annotations

import pandas as pd

from . import spatial


def detect_homes(df: pd.DataFrame, res: int, night_hours: tuple[int, int] = (22, 5),
                 min_nights: int = 1) -> pd.DataFrame:
    """Detect one home H3 cell per device.

    Parameters
    ----------
    df : cleaned mobility frame with ``maid, date, hour, longitude, latitude``.
    res : H3 resolution for the home cell.
    night_hours : (start, end) hour window, wraps midnight (e.g. 22–05);
        ``None`` = use all hours.
    min_nights : min distinct nights a device must appear in to receive a home.

    Returns
    -------
    DataFrame ``[maid, home_h3, home_lon, home_lat, n_home_pings, n_nights]``.
    """
    d = df[["maid", "date", "hour", "longitude", "latitude"]].copy()
    d = d.dropna(subset=["longitude", "latitude"])

    if night_hours is not None:
        start, end = night_hours
        if start <= end:
            d = d[d["hour"].between(start, end)]
        else:  # wraps midnight, e.g. 22–05
            d = d[(d["hour"] >= start) | (d["hour"] <= end)]

    if d.empty:
        return pd.DataFrame(columns=["maid", "home_h3", "home_lon", "home_lat",
                                     "n_home_pings", "n_nights"])

    d["h3"] = spatial.to_h3_cells(d["longitude"].to_numpy(),
                                  d["latitude"].to_numpy(), res)

    # (maid, cell) ping counts, then most frequent cell per maid.
    counts = d.groupby(["maid", "h3"], sort=False).size().rename("n").reset_index()
    homes = counts.sort_values("n").drop_duplicates("maid", keep="last")
    homes = homes.rename(columns={"h3": "home_h3", "n": "n_home_pings"})

    nights = d.groupby("maid")["date"].nunique().rename("n_nights")
    homes = homes.merge(nights, on="maid", how="left")
    if min_nights > 1:
        homes = homes[homes["n_nights"] >= min_nights]

    # Centroid of the home cell (lon/lat for distance calculations).
    lats, lons = spatial.grid_centroids(homes["home_h3"])
    homes["home_lat"], homes["home_lon"] = lats, lons
    return homes.reset_index(drop=True)
