"""Data-cleaning rules shared by every dataset.

Known quirks of the UGM mobility data are encoded here so that every entry
point (script, notebook, future datasets) applies identical cleaning.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# In the legacy Parquet, a few rows leak a raw header string:
#   maid == 'maid', timestamp == 'timestamp', empty lat/lon.
ARTIFACT_TIMESTAMP = "timestamp"

# In the people-graph files missing values are the literal string "\\N".
MISSING_LITERAL = "\\N"

# Column order of the headerless people-graph CSV (see config.PEOPLE_CSV_COLUMNS).


def clean_mobility(df: pd.DataFrame) -> pd.DataFrame:
    """Drop artifact rows and add datetime/date/hour convenience columns.

    Safe to run on any mobility frame that has ``maid, latitude, longitude,
    timestamp`` (timestamp as unix seconds, string or int).
    """
    df = df[df["timestamp"].astype(str) != ARTIFACT_TIMESTAMP].copy()
    df = df.dropna(subset=["latitude", "longitude"]).copy()
    df = df.reset_index(drop=True)

    ts = pd.to_numeric(df["timestamp"], errors="coerce").astype("Int64")
    df["datetime"] = pd.to_datetime(ts, unit="s")
    df["date"] = df["datetime"].dt.normalize()
    df["hour"] = df["datetime"].dt.hour
    return df


def speed_outlier_mask(df: pd.DataFrame, max_kph: float = 120.0,
                       min_gap_min: float = 0.1) -> np.ndarray:
    """Flag pings that imply an implausible travel speed.

    For each ping, compares it to the previous ping of the same device: if the
    implied speed (great-circle distance / time gap) exceeds ``max_kph`` and
    the gap is at least ``min_gap_min``, the ping is flagged as an outlier.

    This removes the **GPS spikes** seen in the raw data (short-gap jumps of
    several km, sometimes ~10^5 km/h) while keeping genuine long trips, whose
    gaps are longer and speeds plausible.

    The returned mask is aligned to ``df``'s original row order.
    """
    # Track original positions through the internal sort so the mask lines up
    # with the caller's frame.
    orig = df.reset_index(drop=True)
    d = orig.sort_values(["maid", "timestamp"])

    g = d.groupby("maid", sort=False)
    ts = pd.to_numeric(d["timestamp"], errors="coerce")
    prev_lon = g["longitude"].shift(1)
    prev_lat = g["latitude"].shift(1)
    prev_ts = pd.to_numeric(g["timestamp"].shift(1), errors="coerce")

    gap_h = (ts - prev_ts) / 3600.0
    dist = _haversine_km(d["longitude"], d["latitude"], prev_lon, prev_lat)
    with np.errstate(divide="ignore", invalid="ignore"):
        speed = np.where(gap_h.to_numpy() > 0, dist / gap_h.to_numpy(), np.nan)
    flag = (speed > max_kph) & (gap_h.to_numpy() * 60 >= min_gap_min)

    out = np.zeros(len(orig), dtype=bool)
    out[d.index.to_numpy()] = np.asarray(flag, dtype=bool)
    return out


def filter_speed_outliers(df: pd.DataFrame, max_kph: float = 120.0,
                          min_gap_min: float = 0.1) -> pd.DataFrame:
    """Return ``df`` with implausible-speed pings removed (per device)."""
    mask = speed_outlier_mask(df, max_kph=max_kph, min_gap_min=min_gap_min)
    return df[~mask].reset_index(drop=True)


def _haversine_km(lon1, lat1, lon2, lat2) -> np.ndarray:
    """Haversine distance in km (vectorised; NaN-safe)."""
    R = 6371.0
    lon1, lat1, lon2, lat2 = map(np.radians, [lon1, lat1, lon2, lat2])
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 2 * R * np.arcsin(np.clip(np.sqrt(a), 0, 1))


def clean_people(df: pd.DataFrame) -> pd.DataFrame:
    """Normalise missing values (literal '\\N' -> pd.NA).

    Rows are NOT unique per ``maid`` — use :func:`profiles` for device-level
    statistics.
    """
    return df.replace({MISSING_LITERAL: pd.NA})


def profiles(df: pd.DataFrame) -> pd.DataFrame:
    """One row per device (first profile row wins)."""
    return df.drop_duplicates("maid")
