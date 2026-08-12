"""I/O layer.

Heavy CSV ingestion uses **DuckDB** (parallel, streaming, low memory) instead
of ``pandas.read_csv``. Loaders return pandas/GeoPandas frames for analysis.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import duckdb
import geopandas as gpd
import pandas as pd

from . import clean, config


# --------------------------------------------------------------------------- #
# CSV -> Parquet (DuckDB, fast)
# --------------------------------------------------------------------------- #

def mobility_csvs_to_parquet(csv_paths: Sequence[str | Path],
                             parquet_path: str | Path,
                             drop_artifact: bool = True) -> Path:
    """Convert one or more mobility CSVs (same header) into one cleaned Parquet.

    Column order is assumed to be ``maid, latitude, longitude, timestamp``
    (matches ``Oktober2021.csv``). A month split across several CSVs (e.g.
    ``November2021_part1..7.csv``) can be passed as a list and lands in a
    single Parquet file.
    """
    paths = [str(Path(p)).replace("'", "''") for p in csv_paths]
    parquet_path = Path(parquet_path)
    parquet_path.parent.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect()
    try:
        # Defensive filters: the legacy parquet carries artifact rows ('timestamp'
        # string) and the raw CSV has embedded header lines mid-file, so we
        # (a) compare on the VARCHAR cast and (b) skip rows that fail parsing.
        where = "WHERE CAST(timestamp AS VARCHAR) <> 'timestamp'" if drop_artifact else ""
        csv_list = ", ".join(f"'{p}'" for p in paths)
        out_q = str(parquet_path).replace("'", "''")
        sql = f"""
            COPY (
                SELECT maid, CAST(latitude AS DOUBLE)  AS latitude,
                       CAST(longitude AS DOUBLE) AS longitude,
                       CAST(timestamp AS BIGINT) AS timestamp
                FROM read_csv_auto([{csv_list}], header = true, ignore_errors = true)
                {where}
            ) TO '{out_q}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """
        con.execute(sql)
    finally:
        con.close()
    return parquet_path


def mobility_csv_to_parquet(csv_path: str | Path, parquet_path: str | Path,
                            drop_artifact: bool = True) -> Path:
    """Convert a single mobility CSV (with header) to a cleaned Parquet file."""
    return mobility_csvs_to_parquet([csv_path], parquet_path,
                                    drop_artifact=drop_artifact)


def people_csv_to_parquet(csv_path: str | Path, parquet_path: str | Path,
                          columns: list[str] | None = None) -> Path:
    """Convert a headerless people-graph CSV to Parquet.

    ``columns`` defaults to ``config.PEOPLE_CSV_COLUMNS`` (11 fields).
    """
    csv_path = Path(csv_path)
    parquet_path = Path(parquet_path)
    parquet_path.parent.mkdir(parents=True, exist_ok=True)

    cols = columns or config.PEOPLE_CSV_COLUMNS
    col_names = ", ".join(f'"{c}"' for c in cols)
    col_spec = ", ".join(f"'{c}': 'VARCHAR'" for c in cols)
    con = duckdb.connect()
    try:
        csv_q = str(csv_path).replace("'", "''")
        out_q = str(parquet_path).replace("'", "''")
        sql = f"""
            COPY (
                SELECT {col_names}
                FROM read_csv_auto('{csv_q}', header = false,
                                   columns = {{{col_spec}}},
                                   ignore_errors = true)
            ) TO '{out_q}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """
        con.execute(sql)
    finally:
        con.close()
    return parquet_path


# --------------------------------------------------------------------------- #
# Loaders
# --------------------------------------------------------------------------- #

def load_mobility(path: str | Path | None = None, *, geom: bool = False,
                  columns: list[str] | None = None) -> pd.DataFrame | gpd.GeoDataFrame:
    """Load the cleaned mobility parquet.

    By default returns a plain DataFrame (fast). Set ``geom=True`` to get a
    GeoDataFrame with a ``geometry`` column (requires a geometry-bearing
    parquet, e.g. the legacy ``oktober_2021.parquet.gzip``).
    """
    path = Path(path) if path else config.DEFAULT_MOBILITY_PARQUET
    if geom:
        gdf = gpd.read_parquet(path, columns=columns)
        return clean.clean_mobility(gdf)
    df = pd.read_parquet(path, columns=columns)
    return clean.clean_mobility(df)


def load_people(path: str | Path | None = None) -> pd.DataFrame:
    """Load the people-graph parquet with missing values normalised."""
    path = Path(path) if path else config.DEFAULT_PEOPLE_PARQUET
    return clean.clean_people(pd.read_parquet(path))


def inspect_csv(csv_path: str | Path, header: bool = True, n: int = 5) -> pd.DataFrame:
    """Peek at a CSV schema without loading it fully (DuckDB)."""
    con = duckdb.connect()
    try:
        return con.execute(
            f"SELECT * FROM read_csv_auto(?, header = {str(header).lower()}) LIMIT {int(n)}",
            [str(csv_path)],
        ).df()
    finally:
        con.close()
