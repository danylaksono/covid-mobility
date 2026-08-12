# Workflow & instructions

How to reproduce the analysis, avoid known pitfalls, and add new data later.
**Architecture & conventions: see [`AGENTS.md`](../AGENTS.md).**

## 1. Environment setup (once)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -e .          # makes `import mobility` work from anywhere
```

## 2. Pipeline steps

Fast path — run the whole pipeline in one go (ingests CSVs, then
H3/OD/metrics/contacts):

```powershell
python scripts/run_all.py --sample 500000   # quick smoke test
python scripts/run_all.py                    # full data (omit --sample)
```

Step-by-step:

```powershell
# 2a. Sanity-check any dataset
python scripts/explore_data.py --quick

# 2b. Raw CSVs -> cleaned parquet (DuckDB; recursive, month-grouped)
python scripts/process_mobility.py --raw-dir data/raw --people data/raw/people_graph.csv --out data/parquet
#     multi-part months (e.g. November2021_part1..7) are combined into one
#     mobility_<MonthYear>.parquet; a combined mobility.parquet is also rebuilt

# 2c. Full-data profile: ALL aggregates on the whole dataset (chunked)
python scripts/profile_full.py --out data/processed --people data/parquet/people.parquet
#     The full 292M-row frame does NOT fit in RAM (~31 GB machine); this script
#     processes data in date-chunks and writes the same outputs as
#     prepare_spatial.py + compute_metrics.py + compute_contacts.py.
#     --start-date/--end-date   restrict to a window (dry-run)
#     --chunk-rows 30000000     chunk size in pings (tune to available RAM)

# 2d. Spatial aggregates: H3 grids + OD flows + static maps
python scripts/prepare_spatial.py --out data/processed --plot outputs/maps
#     --sample 500000   quick smoke test
#     --res 9           finer hexagons (~0.18 km)

# 2e. Home cells + per-device-day mobility metrics
python scripts/compute_metrics.py --out data/processed --res 8
#     --sample 500000   quick smoke test
#     --night-hours 22,5   home-detection night window (default 22:00-05:00)

# 2f. Static summary plots (from the prepared data)
python scripts/plot_summary.py --out outputs/plots --report outputs/report_summary.png

# 2g. Per-device movement traces (confirms devices move; uses data/geo boundaries)
python scripts/plot_traces.py --day 2021-10-30 --n 5 --pick mix --layout single --max-speed-kph 120 --out outputs/traces
python scripts/plot_traces.py --day 2021-10-30 --n 5 --pick mix --layout grid  --max-speed-kph 120 --out outputs/traces

# 2h. Thin visualisation notebook (loads prepared data, static plots only)
code notebooks/UGM_Mobility_Data_Analysis.ipynb
```

## 3. Notebook rules

- Run cells **top-to-bottom**; the notebook shares kernel state.
- The notebook is **visualisation-only**: if it needs new processing, add a
  function to `src/mobility/` (or a script) instead of inline.
- If the H3-grid or metrics cell prints "not found", run steps 2c / 2d first.

## 4. Add new data later (Oct 2021 → Jun 2022)

The raw data now lives in per-month folders under `data/raw/Data GPS/`, e.g.
`2021November/November2021_part1.csv` … `part7.csv` (some months are split
into parts). `process_mobility.py --raw-dir` discovers these recursively.

1. Copy new CSVs into `data/raw/` (keep the `Data GPS/<Month>/<Month>_partN.csv`
   layout; files can sit in sub-folders — `--raw-dir` recurses).
2. `python scripts/process_mobility.py --raw-dir data/raw --people data/raw/people_graph.csv --out data/parquet`
   - One `data/parquet/mobility_<MonthYear>.parquet` per month; parts combined.
   - Byte-identical duplicates are dropped (e.g. the `Oktober2021.csv` copy at
     `data/raw` root vs its month folder; and `November2021_part6.csv` is an
     exact copy of `part4` — ingested once to avoid double counting).
   - Combined `data/parquet/mobility.parquet` is rebuilt from all months.
3. Re-run `prepare_spatial.py` / `compute_metrics.py` if the aggregates should
   include the new months (they read `data/parquet/mobility.parquet`).
4. If the schema differs from the known conventions (see
   `docs/DATA_STRUCTURE.md`), extend `mobility.io` / `mobility.clean`, then
   update `docs/DATA_STRUCTURE.md` and `AGENTS.md`.
5. Append a dated section to `FINDINGS.md` rather than overwriting.

> **May 2022 (Mei)** is now ingested: `Mei2022_part1/2.csv` live under
> `data/raw/Data GPS/2022Mei/OneDrive_1_12-08-2026/` (a nested folder —
> `--raw-dir` recurses into it). Re-running step 2 is **incremental**: months
> whose parquet is already up to date are reused, so only new/changed months
> are re-ingested (pass `--force` to re-ingest everything).

## 5. Known pitfalls

- **h3 is scalar-only** in this build — always use `mobility.spatial.to_h3_cells`
  (wraps `np.frompyfunc`), never call `h3.latlng_to_cell` on arrays.
- **`people_graph.csv` is headerless** — `mobility.io.people_csv_to_parquet`
  passes explicit columns (`config.PEOPLE_CSV_COLUMNS`).
- **Artifact rows / `\N`** — handled by `mobility.clean`; always go through it.
- **Big data** — prefer DuckDB queries over pandas for aggregations
  (`mobility.temporal` does this). Loading 12M rows into pandas is fine for a
  one-off plot, not for iterative analysis.
