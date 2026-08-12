# Data structure & metadata

This document describes every data file in `data/` and how the columns are
interpreted. Use it as the reference when extending the analysis or adding new
data.

## Files

| Path                                     | Format                 | Size         | Rows        | Description                                          |
| ---------------------------------------- | ---------------------- | ------------ | ----------- | ---------------------------------------------------- |
| `data/raw/Oktober2021.csv`               | CSV                    | ~889 MB      | 12,123,733  | Raw mobility pings (source of truth)                 |
| `data/raw/people_graph.csv`              | CSV                    | ~239 MB      | 1,834,289   | Raw device profiles (source of truth)                |
| `data/legacy/oktober_2021.parquet.gzip`  | Parquet (GeoPandas)    | ~237 MB      | 12,123,733  | Legacy mobility parquet with `geometry` (read-only)  |
| `data/legacy/oktober2021.parquet`        | Parquet (pandas)       | ~339 MB      | 12,123,733  | Same rows, **no** geometry column                    |
| `data/legacy/oktober2021gz.parquet.gzip` | Parquet (pandas, gzip) | ~193 MB      | 12,123,733  | Same rows, no geometry, compressed                   |
| `data/legacy/people_graph.parquet`       | Parquet (pandas)       | ~75 MB       | 1,834,289   | Legacy device profiles (read-only)                   |
| `data/parquet/mobility.parquet`          | Parquet (pipeline)     | ~3.6 GB      | 292,226,383 | Cleaned pings, **all months** (DuckDB ingest)        |
| `data/parquet/mobility_<Month>.parquet`  | Parquet (pipeline)     | 13 MB–1.1 GB | varies      | Cleaned pings per month (multi-part months combined) |
| `data/parquet/people.parquet`            | Parquet (pipeline)     | ~45 MB       | 1,834,289   | Cleaned profiles (`\N` → NULL)                       |

> The three **legacy** mobility Parquet files cover **October 2021 only** (same
> 12,123,733 raw rows; 24 artifact rows are removed on cleaning → 12,123,709).
> `data/parquet/mobility.parquet` is the **pipeline** version (no `geometry`,
> timestamp as BIGINT), covering **23 Oct 2021 → 7 Jun 2022** (all months,
> incl. May 2022).

Per-month pipeline files (`data/parquet/mobility_<MonthYear>.parquet`):

| File                    | Size (MB) | Rows            | Devices   | Period (UTC)            |
| ----------------------- | --------- | --------------- | --------- | ----------------------- |
| `mobility_Oktober2021`  | ~149      | 12,123,709      | 398,142   | 2021-10-23 → 2021-10-31 |
| `mobility_November2021` | ~1,122    | 100,853,463     | 1,226,198 | 2021-11-01 → 2021-11-30 |
| `mobility_Desember2021` | ~625      | 45,950,349      | 1,288,665 | 2021-12-01 → 2021-12-31 |
| `mobility_Januari2022`  | ~325      | 22,488,993      | 924,855   | 2022-01-01 → 2022-01-31 |
| `mobility_Februari2022` | ~538      | 39,601,777      | 956,296   | 2022-02-01 → 2022-02-28 |
| `mobility_Maret2022`    | ~269      | 26,837,642      | 457,977   | 2022-03-01 → 2022-03-31 |
| `mobility_April2022`    | ~13       | 1,048,571       | 121,764   | 2022-04-01 → 2022-04-30 |
| `mobility_Mei2022`      | ~413      | 31,075,618      | 1,271,675 | 2022-05-01 → 2022-05-31 |
| `mobility_Juni2022`     | ~166      | 12,246,261      | 403,758   | 2022-06-01 → 2022-06-07 |
| **combined**            | ~3,621    | **292,226,383** | ~4.3M     | 2021-10-23 → 2022-06-07 |

## Mobility file — columns

| Column      | Type          | Description                                                                         |
| ----------- | ------------- | ----------------------------------------------------------------------------------- |
| `maid`      | string (UUID) | Mobile Advertising ID — pseudonymous device identifier                              |
| `latitude`  | float         | WGS84 latitude (deg)                                                                |
| `longitude` | float         | WGS84 longitude (deg)                                                               |
| `timestamp` | string (int)  | Unix time (seconds), stored as a string; parse with `pd.to_datetime(int, unit='s')` |
| `geometry`  | Point         | Shapely point (`longitude, latitude`) — only in the GeoPandas variant               |

**Caveats:**

- **24 artifact rows** exist where `timestamp == 'timestamp'` (a leaked raw
  header row: `maid='maid'`, empty geometry). Always filter
  `mobility = mobility[mobility['timestamp'] != 'timestamp']`.
- Timestamps are treated as **UTC** in the notebook. Local time in DIY is
  UTC+7 (WIB).
- Coverage is **not uniform** across days: 23–25 Oct have far fewer active
  devices than 29–31 Oct (see `FINDINGS.md`).
- **GPS outliers**: ~0.3% of pings imply implausible travel speed (short-gap
  multi-km jumps, occasionally ~10⁵ km/h). Remove with
  `mobility.clean.filter_speed_outliers(df, max_kph=120)` before tracing.

## People-graph file — columns

| Column         | Type          | Description                                                                                           |
| -------------- | ------------- | ----------------------------------------------------------------------------------------------------- |
| `maid`         | string (UUID) | Device identifier (join key to mobility)                                                              |
| `sex`          | string        | `male` / `female`; missing = `\N`                                                                     |
| `col3`, `col4` | string        | Unused / unknown columns (all `\N` in the sample)                                                     |
| `country`      | string        | ISO country code (`IDN`)                                                                              |
| `phone_id`     | string        | Obfuscated phone identifier                                                                           |
| `intensity`    | string        | Activity intensity: `low` / `medium` / `high`; missing = `\N`                                         |
| `province`     | string        | `Daerah Istimewa Yogyakarta`                                                                          |
| `place1`       | string        | Regency / city (kabupaten/kota): `Sleman`, `Kota Yogyakarta`, `Bantul`, `Gunung Kidul`, `Kulon Progo` |
| `place2`       | string        | District (kecamatan), e.g. `Gamping`, `Pleret`                                                        |
| `place3`       | string        | Village / sub-district (kelurahan/desa), e.g. `Nogotirto`, `Bawuran`                                  |

**Caveats:**

- Missing values are the **literal string `\N`**, not `NaN` — replace with
  `pd.NA` before analysis:
  `people = people.replace({'\\N': pd.NA})`.
- **Rows are not unique per `maid`**: 1→1 row for ~851k maids, 2→234k, 3→126k,
  4→34k. Use `drop_duplicates('maid')` for device-level stats.
- `col3` / `col4` are undocumented; treat as noise unless a data dictionary
  for the source appears.

## Key join

```python
profile = people.replace({'\\N': pd.NA}).drop_duplicates('maid')
merged = mobility.merge(profile[['maid', 'sex', 'intensity', 'place1']],
                        on='maid', how='left')
```

Overlap: **133,908** maids appear in both datasets (~34% of mobility devices).

## Pipeline output conventions (new)

`scripts/` write cleaned / aggregated data to the following locations
(defined in `src/mobility/config.py`):

| Path                                                        | Contents                                                                                                               |
| ----------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| `data/raw/`                                                 | Source CSVs in per-month folders (`Data GPS/<Month>/`, some months in `_partN` parts)                                  |
| `data/parquet/mobility.parquet`                             | Cleaned pings, all months: `maid, latitude, longitude, timestamp` (BIGINT) — no geometry                               |
| `data/parquet/mobility_<MonthYear>.parquet`                 | Cleaned pings per month (parts combined), e.g. `mobility_November2021.parquet`                                         |
| `data/parquet/people.parquet`                               | Cleaned profiles: `\N` → NULL, same 11 columns                                                                         |
| `data/processed/h3_grid_r<res>_daily.parquet`               | `date, h3, count` — H3 cell density per day (h3 = string id)                                                           |
| `data/processed/concentration_r<res>.parquet`               | `date, hhi, gini` — daily spatial concentration of pings across H3 cells                                               |
| `data/processed/od_device_day_r<res>.parquet`               | `maid, date, origin, dest, n_pings` — one trip per device-day                                                          |
| `data/processed/od_flows_r<res>.parquet`                    | `date, origin, dest, n_devices, n_pings, od_distance_km` — aggregated directed flows + cell-centroid distance          |
| `data/processed/od_corridor_change_r<res>.parquet`          | `date, origin, dest, n_pings, n_pings_baseline, n_pings_pct_change, is_baseline` — per-corridor % change vs baseline   |
| `data/processed/od_flows_district_r<res>.parquet`           | `date, origin_place<level>, dest_place<level>, n_devices, n_pings` — district-level flows (from `--people`)            |
| `data/processed/od_net_flows_district_r<res>.parquet`       | `date, pair_a, pair_b, net_n_pings` — net directional flow per district pair                                           |
| `data/processed/homes_r<res>.parquet`                       | `maid, home_h3, home_lon, home_lat, n_home_pings, n_nights` — home cell per device (baseline nights)                   |
| `data/processed/metrics_device_day_r<res>.parquet`          | `maid, date, n_pings, n_cells, n_trips, radius_km, max_dist_home_km, stay_at_home` — per-device-day mobility metrics   |
| `data/processed/mobility_index_r<res>.parquet`              | `date, <metrics>, <metrics>_baseline, <metrics>_pct_change, is_baseline` — daily summary + % change vs baseline window |
| `data/processed/mobility_index_by_place1_r<res>.parquet`    | same, stratified by regency (`place1`)                                                                                 |
| `data/processed/contacts_occupancy_r<res>_<bucket>.parquet` | `bucket, h3, n_devices, n_pings` — devices per (time window, cell)                                                     |
| `data/processed/meeting_index_r<res>_<bucket>.parquet`      | `bucket, meeting_index` — pairwise co-locations per time window                                                        |
| `data/processed/meeting_index_daily_r<res>.parquet`         | `date, meeting_index` — same, per day                                                                                  |
| `data/processed/crowding_r<res>_<bucket>.parquet`           | `bucket, cells_n2, cells_n5, cells_n10, cells_n20` — #cells with ≥ k devices per window                                |

The legacy `data/legacy/` files remain **read-only** inputs; the pipeline
reads them by default until re-ingested from `data/raw/`.

> **Status (2026-08-12):** `data/processed/` now contains **full-window**
> outputs over all nine months (23 Oct 2021 → 7 Jun 2022, 292,226,383 pings),
> produced by `scripts/profile_full.py` in two RAM-bounded date-chunks passes
> (run log: `data/processed/_profile_run.log`). The earlier **500k-row smoke
> test** outputs have been superseded — these files are full-data, not
> sample-based. See `FINDINGS.md` §9 for the headline numbers.
