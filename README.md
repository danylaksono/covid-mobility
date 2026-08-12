# UGM Mobility Data Analysis — Yogyakarta (COVID-19)

Analysis of anonymous mobile-device GPS mobility data collected in the
**Daerah Istimewa Yogyakarta (DIY)**, Indonesia, during the **COVID-19
pandemic**. The core dataset covers **23 October 2021 → 7 June 2022** (nine
months of pings) and is paired with a **people graph** (device-level
demographics / activity intensity).

> Context: this is a COVID-19 mobility study. When interpreting results, keep
> in mind the pandemic policy timeline for Indonesia (PSBB / PPKM restrictions,
> mobility caps, work-from-home, school closures) across the study window
> (Oct 2021 – Jun 2022).

> Status (2026-08-12): all nine months (23 Oct 2021 → 7 Jun 2022) are ingested
> and the full-window profile run is complete — see [`FINDINGS.md`](FINDINGS.md) §9.

## Repository layout

```
mobility/
├── AGENTS.md                          # agent guide: architecture, conventions, roadmap
├── research_plan.md                   # analysis plan (COVID themes + viz roadmap)
├── notebooks/
│   └── UGM_Mobility_Data_Analysis.ipynb   # thin visualisation notebook (static plots only)
├── web/                              # interactive trace inspector (MapLibre GL JS)
│   └── see web/README.md
├── src/mobility/                      # reusable processing package (DuckDB + H3)
│   ├── config.py  io.py  clean.py
│   ├── temporal.py  spatial.py  od.py
│   └── homes.py  metrics.py  contacts.py
├── scripts/                           # pipeline steps (CLI)
│   ├── process_mobility.py            #   raw CSVs -> cleaned parquet
│   ├── prepare_spatial.py             #   H3 grids + OD flows + static maps
│   ├── compute_metrics.py             #   homes + per-device-day metrics
│   ├── compute_contacts.py            #   meeting index + crowding
│   ├── profile_full.py                #   full-window aggregates (RAM-bounded)
│   ├── run_all.py                     #   run the whole pipeline in one go
│   ├── plot_summary.py / plot_traces.py   #   static summary plots / traces
│   ├── export_traces_web.py           #   web-viewer data (geojson)
│   └── explore_data.py                #   sanity-check any dataset
├── FINDINGS.md                        # analysis findings
├── requirements.txt  pyproject.toml
├── docs/                              # DATA_STRUCTURE.md, WORKFLOW.md
├── data/                              # raw/ parquet/ processed/ legacy/
└── archive/                           # versioned old notebooks (read-only)
```

**Separation of concerns:** all heavy data processing lives in `src/mobility`
and `scripts/` (DuckDB for ingestion/aggregation, H3 for spatial). Notebooks
only load prepared Parquet and produce static plots — no interactive maps.

## Quick start

```powershell
# 1. Create & activate a virtual environment (Python 3.14 tested)
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. Install dependencies + the local package
pip install -r requirements.txt
pip install -e .

# 3. Explore the data (prints an overview of any dataset)
python scripts/explore_data.py

# 4. Build the spatial aggregates (H3 grids + OD flows + static maps)
python scripts/prepare_spatial.py --out data/processed --plot outputs/maps

# 5. Build home cells + per-device-day mobility metrics
python scripts/compute_metrics.py --out data/processed --res 8

# 6. Open the (thin) notebook and run cells top-to-bottom
code notebooks/UGM_Mobility_Data_Analysis.ipynb
```

Raw CSVs (Oct 2021 → Jun 2022) live in `data/raw/`. To (re)ingest them into
cleaned parquet, or to add a new month, drop the CSVs into `data/raw/` and run
the whole pipeline in one go:

```powershell
python scripts/run_all.py --sample 500000   # quick smoke test
python scripts/run_all.py                    # full data
```

(or step-by-step: `process_mobility.py` → `prepare_spatial.py` →
`compute_metrics.py` → `compute_contacts.py`). See
[`docs/WORKFLOW.md`](docs/WORKFLOW.md), [`AGENTS.md`](AGENTS.md) and
[`research_plan.md`](research_plan.md) for details.

## Key facts

| Item                           | Value                              |
| ------------------------------ | ---------------------------------- |
| Mobility records (cleaned)     | 292,226,383                        |
| Unique devices (maids)         | ~4.28M                             |
| Time window                    | 2021-10-23 → 2022-06-07 (UTC)      |
| Days covered                   | 228                                |
| Devices with a home cell       | 2,496,775                          |
| Device-days                    | 17,943,752                         |
| Overall stay-at-home rate      | ~42.7%                             |
| Spatial extent (deg)           | lon 110.00–110.83, lat −8.20–−7.56 |
| People-graph profiles (unique) | ~1,245k                            |
| Mobility ↔ people overlap      | ~900k devices                      |

See [`FINDINGS.md`](FINDINGS.md) for the analysis results and
[`docs/DATA_STRUCTURE.md`](docs/DATA_STRUCTURE.md) for full metadata.
