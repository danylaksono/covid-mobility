"""Spatial aggregation with Uber H3 hexagons.

All heavy aggregation happens here (or in ``scripts/prepare_spatial.py``) and
is cached to Parquet. Notebooks only plot the cached grids.

The installed ``h3`` build (v4, Windows / py3.14) exposes a **scalar, string
API** only, so we wrap ``latlng_to_cell`` with ``numpy.frompyfunc`` to
vectorise it (~1.2M points/sec — 12M points take ~10 s). Cell ids are plain
strings (e.g. ``'888d8cb95dfffff'``), which are Parquet-friendly.
"""

from __future__ import annotations

import h3
import numpy as np
import pandas as pd

# Vectorised wrapper: returns an object array of h3 cell strings.
_latlng_to_cell_vec = np.frompyfunc(h3.latlng_to_cell, 3, 1)


def to_h3_cells(lons, lats, res: int) -> np.ndarray:
    """lon/lat arrays -> ndarray of h3 cell strings."""
    lons = np.asarray(lons, dtype=np.float64).ravel()
    lats = np.asarray(lats, dtype=np.float64).ravel()
    return _latlng_to_cell_vec(lats, lons, res)


def aggregate_grid(df: pd.DataFrame, res: int,
                   time_bucket: str | None = None) -> pd.DataFrame:
    """Aggregate pings into (``time_bucket``, h3 cell) counts.

    Parameters
    ----------
    df : DataFrame with ``longitude`` / ``latitude`` columns.
    res : H3 resolution.
    time_bucket : optional column (e.g. ``"date"``) to split the grid by.

    Returns
    -------
    DataFrame with columns ``[time_bucket?, h3, count]``; ``h3`` is a string id.
    """
    d = df[["longitude", "latitude"]].copy()
    if time_bucket is not None:
        d[time_bucket] = df[time_bucket]

    d["h3"] = to_h3_cells(d["longitude"].to_numpy(), d["latitude"].to_numpy(), res)
    keys = ["h3"] if time_bucket is None else [time_bucket, "h3"]
    out = d.groupby(keys, sort=True).size().rename("count").reset_index()
    return out


def grid_centroids(cells) -> tuple[np.ndarray, np.ndarray]:
    """Iterable of h3 cell strings -> (lats, lons) centroid arrays."""
    cells = list(cells)
    lats, lons = np.empty(len(cells)), np.empty(len(cells))
    for i, c in enumerate(cells):
        lat, lon = h3.cell_to_latlng(c)
        lats[i], lons[i] = lat, lon
    return lats, lons


def grid_boundaries(cells, crs: str = "EPSG:4326"):
    """h3 cell strings -> GeoDataFrame of hexagon polygons."""
    import geopandas as gpd
    from shapely.geometry import Polygon

    cells = list(cells)
    polys = []
    for c in cells:
        verts = h3.cell_to_boundary(c)  # list of (lat, lng)
        polys.append(Polygon([(lng, lat) for lat, lng in verts]))
    return gpd.GeoDataFrame({"h3": cells}, geometry=polys, crs=crs)


# --------------------------------------------------------------------------- #
# Concentration (Gini / Herfindahl) — how concentrated is activity?
# --------------------------------------------------------------------------- #

def _gini(values) -> float:
    """Population Gini coefficient: 1 - 2 * (area under the Lorenz curve).

    0 = perfectly equal distribution, 1 = all mass in one cell.
    """
    s = np.sort(np.asarray(values, dtype=float))
    n = s.size
    total = s.sum()
    if n == 0 or total <= 0:
        return np.nan
    lorenz = np.concatenate([[0.0], np.cumsum(s) / total])
    area = np.trapezoid(lorenz, np.linspace(0.0, 1.0, n + 1))
    return float(1 - 2 * area)


def concentration(grid: pd.DataFrame, value_col: str = "count",
                  group_cols: list[str] | None = None,
                  measures: tuple[str, ...] = ("hhi", "gini")) -> pd.DataFrame:
    """Concentration of ``value_col`` across cells, per group (or overall).

    Parameters
    ----------
    grid : ``aggregate_grid`` output (``[group_cols?], h3, <value_col>``).
    value_col : column holding the per-cell counts (default ``"count"``).
    group_cols : optional grouping, e.g. ``["date"]`` for a daily index.
    measures : which indices to compute.

    Returns
    -------
    DataFrame with the group columns (if any) and one column per measure:
    - ``hhi`` : Herfindahl index = sum of squared shares
      (0 = spread uniformly, 1 = everything in one cell).
    - ``gini`` : Gini coefficient (0 = equal, 1 = maximally concentrated).
    """
    keys = list(group_cols or [])
    out: dict[str, pd.Series] = {}
    if not keys:
        # Overall concentration (single group over all cells).
        s = grid[value_col]
        if "hhi" in measures:
            out["hhi"] = pd.Series([float(((s / s.sum()) ** 2).sum())])
        if "gini" in measures:
            out["gini"] = pd.Series([_gini(s)])
        return pd.DataFrame(out)
    if "hhi" in measures:
        out["hhi"] = grid.groupby(keys, observed=True)[value_col].apply(
            lambda s: float(((s / s.sum()) ** 2).sum()))
    if "gini" in measures:
        out["gini"] = grid.groupby(keys, observed=True)[value_col].apply(_gini)
    return pd.DataFrame(out).reset_index()

