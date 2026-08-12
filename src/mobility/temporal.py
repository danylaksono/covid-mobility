"""Temporal aggregation.

Aggregations run inside **DuckDB** directly against the Parquet files, so the
full 12M+ rows never need to be materialised in Python. Add new aggregate
helpers here rather than in notebooks.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from . import config


def _con() -> duckdb.DuckDBPyConnection:
    return duckdb.connect()


def daily_counts(parquet_path: str | Path | None = None) -> pd.DataFrame:
    """Pings and active devices per day (all clean rows)."""
    path = Path(parquet_path) if parquet_path else config.DEFAULT_MOBILITY_PARQUET
    con = _con()
    try:
        q = """
            SELECT to_timestamp(CAST(timestamp AS BIGINT))::DATE AS date,
                   count(*)                       AS pings,
                   count(DISTINCT maid)           AS devices
            FROM read_parquet(?) AS t
            WHERE CAST(timestamp AS VARCHAR) <> 'timestamp'
              AND latitude  IS NOT NULL
              AND longitude IS NOT NULL
            GROUP BY 1 ORDER BY 1
        """
        return con.execute(q, [str(path)]).df()
    finally:
        con.close()


def hourly_counts(parquet_path: str | Path | None = None) -> pd.DataFrame:
    """Pings per hour across the whole window (for the crisis/COVID timeline)."""
    path = Path(parquet_path) if parquet_path else config.DEFAULT_MOBILITY_PARQUET
    con = _con()
    try:
        q = """
            SELECT date_trunc('hour', to_timestamp(CAST(timestamp AS BIGINT))) AS hour,
                   count(*) AS pings
            FROM read_parquet(?) AS t
            WHERE CAST(timestamp AS VARCHAR) <> 'timestamp'
              AND latitude  IS NOT NULL
              AND longitude IS NOT NULL
            GROUP BY 1 ORDER BY 1
        """
        return con.execute(q, [str(path)]).df()
    finally:
        con.close()


def diurnal_profile(parquet_path: str | Path | None = None) -> pd.DataFrame:
    """Mean pings per hour-of-day (diurnal rhythm)."""
    path = Path(parquet_path) if parquet_path else config.DEFAULT_MOBILITY_PARQUET
    con = _con()
    try:
        q = """
            WITH base AS (
                SELECT timestamp, maid,
                       date_part('hour', to_timestamp(CAST(timestamp AS BIGINT))) AS hour
                FROM read_parquet(?) AS t
                WHERE CAST(timestamp AS VARCHAR) <> 'timestamp'
                  AND latitude  IS NOT NULL
                  AND longitude IS NOT NULL
            )
            SELECT hour,
                   count(*) AS pings,
                   count(DISTINCT to_timestamp(CAST(timestamp AS BIGINT))::DATE) AS days
            FROM base GROUP BY 1 ORDER BY 1
        """
        df = con.execute(q, [str(path)]).df()
        df["mean_pings"] = df["pings"] / df["days"]
        return df
    finally:
        con.close()
