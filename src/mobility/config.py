"""Paths and shared constants for the mobility processing pipeline."""

from __future__ import annotations

from pathlib import Path

# Repo root = 3 levels up from src/mobility/config.py
REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"

# New pipeline convention (outputs of scripts/*.py):
RAW_DIR = DATA_DIR / "raw"              # source CSVs (Oct 2021 ... May 2022)
PARQUET_DIR = DATA_DIR / "parquet"      # cleaned parquet (process_mobility.py)
PROCESSED_DIR = DATA_DIR / "processed"  # aggregates: h3 grids, OD matrices

# Legacy pre-processed October-2021 parquet (read-only; produced before this
# repo existed — migrated from the old `data/Parquet` folder).
LEGACY_DIR = DATA_DIR / "legacy"

# Default inputs (legacy pre-processed files; the pipeline can rebuild them
# from data/raw via scripts/process_mobility.py)
DEFAULT_MOBILITY_PARQUET = LEGACY_DIR / "oktober_2021.parquet.gzip"
DEFAULT_PEOPLE_PARQUET = LEGACY_DIR / "people_graph.parquet"

# Typical outputs of the pipeline
MOBILITY_PARQUET = PARQUET_DIR / "mobility.parquet"
PEOPLE_PARQUET = PARQUET_DIR / "people.parquet"
H3_GRID_PARQUET = PROCESSED_DIR / "h3_grid_daily.parquet"
CONCENTRATION_PARQUET = PROCESSED_DIR / "concentration.parquet"
OD_DEVICE_DAY_PARQUET = PROCESSED_DIR / "od_device_day.parquet"
OD_FLOWS_PARQUET = PROCESSED_DIR / "od_flows.parquet"
OD_CORRIDOR_CHANGE_PARQUET = PROCESSED_DIR / "od_corridor_change.parquet"
OD_FLOWS_DISTRICT_PARQUET = PROCESSED_DIR / "od_flows_district.parquet"
OD_NET_FLOWS_PARQUET = PROCESSED_DIR / "od_net_flows_district.parquet"
HOMES_PARQUET = PROCESSED_DIR / "homes.parquet"
METRICS_PARQUET = PROCESSED_DIR / "metrics_device_day.parquet"
MOBILITY_INDEX_PARQUET = PROCESSED_DIR / "mobility_index.parquet"
CONTACTS_OCCUPANCY_PARQUET = PROCESSED_DIR / "contacts_occupancy.parquet"
MEETING_INDEX_PARQUET = PROCESSED_DIR / "meeting_index.parquet"
MEETING_INDEX_DAILY_PARQUET = PROCESSED_DIR / "meeting_index_daily.parquet"
CROWDING_PARQUET = PROCESSED_DIR / "crowding.parquet"

# --------------------------------------------------------------------------- #
# Raw CSV conventions (verified on the Oct-2021 files)
# --------------------------------------------------------------------------- #
# Mobility CSV HAS a header row:   maid,latitude,longitude,timestamp
# People-graph CSV is HEADERLESS: 11 columns in this order:
PEOPLE_CSV_COLUMNS = [
    "maid", "sex", "col3", "col4", "country", "phone_id",
    "intensity", "province", "place1", "place2", "place3",
]

# --------------------------------------------------------------------------- #
# Spatial settings
# --------------------------------------------------------------------------- #
# H3 hexagon resolution used for grid density. Approx. hexagon sizes:
#   res 7 ~ 5.2 km, res 8 ~ 0.66 km, res 9 ~ 0.18 km
H3_RES_GRID = 8        # default grid density resolution
H3_RES_OD = 8          # resolution for origin/destination cells in OD flows
OD_TIME_BUCKET = "date"  # OD is built per device per day
