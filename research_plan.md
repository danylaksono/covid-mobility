# Research Plan — COVID-19 Mobility Analysis (Yogyakarta)

Living plan for the mobility analysis during the COVID-19 pandemic, using the
anonymous GPS dataset from DIY, Indonesia (Oct 2021 → Jun 2022, all months
ingested).
Focus: **preparing derived data for visualization** (including a glyph library
that supports origin–destination datasets).

Related docs: `AGENTS.md` (architecture), `docs/DATA_STRUCTURE.md` (schema),
`FINDINGS.md` (results), `docs/WORKFLOW.md` (how to run).

---

## 1. Goal & scope

- Quantify **how mobility changed during the pandemic** (vs. baseline) in DIY.
- Build **reusable derived datasets** (per-device, per-day, per-flow) that the
  visualization layer — glyphs, OD maps, small multiples — can consume directly.
- **Not** in scope yet: interactive maps / lonboard (static plots only for now).

## 2. Data readiness

| Piece                               | Status                                              |
| ----------------------------------- | --------------------------------------------------- |
| Mobility pings 23–31 Oct 2021       | ✅ prepared (`data/parquet/mobility.parquet`)       |
| People graph                        | ✅ prepared (`data/parquet/people.parquet`)         |
| H3 grid density per day             | ✅ `prepare_spatial.py`                             |
| OD device-day + flows               | ✅ `od.py` + `prepare_spatial.py`                   |
| Home cells + per-device-day metrics | ✅ `homes.py` + `metrics.py` + `compute_metrics.py` |
| Full window (Oct 2021 → Jun 2022)   | ✅ ingested (9 months, 292.2M pings)               |
| Full-data profile (all months)      | ✅ `scripts/profile_full.py` (see `FINDINGS.md` §9) |
| COVID case counts / PPKM timeline   | ⏳ external dataset to add                          |

## 3. Analysis themes

### 3.1 Temporal activity dynamics

- Daily/hourly volume & active devices (have it).
- **Coverage-corrected trends**: pings per active device per day (23–25 Oct is
  a sparse ramp-up — always normalize or annotate).
- **Policy change-points**: PPKM level changes, curfews, holidays; test for
  step changes in the hourly series.
- **Diurnal shift**: do morning/evening peaks move or flatten under
  restrictions (curfew → suppressed night activity)?

### 3.2 Individual / device-level metrics (glyph raw material) ⭐

Per device per day, from `metrics.py`:

- `n_pings` (volume), `n_cells` (visited-location count),
- `n_trips` (cell transitions), `radius_km` (radius of gyration),
- `max_dist_home_km` (farthest from home), `stay_at_home` (never left home cell).
  Stratify by `sex`, `intensity`, `place1/place2` (people graph).

### 3.3 Spatial concentration & dispersion

- Day-over-day H3 density **deltas**.
- **Concentration index** (Gini / Herfindahl of pings across H3 cells) — do
  people crowd into fewer cells during restrictions?
- **Hotspot persistence**: which cells stay dense (essential hubs) vs
  appear/disappear (event-driven).
- Optional: Moran's I over H3 cells as a single clustering number per day.

### 3.4 Origin–destination analysis ⭐ (glyph library's sweet spot)

- **OD matrices** per day (`od.py`).
- **Corridor-level change**: which OD pairs shrank/grew vs. baseline.
- **Mean trip-length distribution** over time (shorter/longer trips?).
- **Net flow / asymmetry** between origins and destinations.
- **OD graph metrics**: degree, betweenness, community detection.
- **District-level OD**: join origin/dest to `place1/place2` → inter-regency
  flows (Sleman → Kota Yogyakarta commute etc.).
- **Essential vs non-essential** trips via time-of-day proxy (no POI data).

### 3.5 COVID policy / public-health metrics

- **Stay-at-home index** and **mobility change from baseline** (Google/Apple
  mobility-report style, per regency).
- **Meeting index / contact proxy**: distinct devices co-located in the same
  H3 cell within ~1 h → exposure proxy over time.
- **High-risk zone flows** (if case data / danger zones are overlaid).
- **Mobility ↔ cases correlation** (needs case-count dataset).

## 4. Derived data products (to add to `data/processed/`)

| Product                                                  | Module / script                       | Status |
| -------------------------------------------------------- | ------------------------------------- | ------ |
| `homes_r8.parquet`                                       | `homes.py` / `compute_metrics.py`     | ✅     |
| `metrics_device_day_r8.parquet`                          | `metrics.py` / `compute_metrics.py`   | ✅     |
| `h3_grid_r8_daily.parquet`                               | `spatial.py` / `prepare_spatial.py`   | ✅     |
| `od_device_day_r8.parquet`                               | `od.py` / `prepare_spatial.py`        | ✅     |
| `od_flows_r8.parquet` (+ `od_distance_km`)               | `od.py` / `prepare_spatial.py`        | ✅     |
| `od_corridor_change_r8.parquet`                          | `od.py` / `prepare_spatial.py`        | ✅     |
| `od_flows_district_r8.parquet` (by `place1/2`)           | `od.py` / `prepare_spatial.py`        | ✅     |
| `od_net_flows_district_r8.parquet`                       | `od.py` / `prepare_spatial.py`        | ✅     |
| `mobility_index_r8.parquet` (+ by `place1`)              | `metrics.py` / `compute_metrics.py`   | ✅     |
| `contacts_occupancy_r8_1h.parquet`                       | `contacts.py` / `compute_contacts.py` | ✅     |
| `meeting_index_*`, `meeting_index_daily_*`, `crowding_*` | `contacts.py` / `compute_contacts.py` | ✅     |
| `concentration_r8.parquet` (Gini/HHI per day)            | `spatial.py` / `prepare_spatial.py`   | ✅     |

## 5. Visualization plan (glyph library)

- **Per-person glyph grid**: one glyph per device (or per regency/cohort),
  channels = `radius_km`, `n_cells`, `max_dist_home_km`, `stay_at_home`,
  `intensity`, `sex`. Shows cohort differences at a glance.
- **OD glyphs**: flows as glyphs with channels for `n_devices`, `n_pings`,
  corridor change vs baseline; ring/sector layouts per origin.
- **Small multiples** per day × region for temporal change.
- **Static maps**: hexbin + H3 grid (already produced by `prepare_spatial.py`).
- **Animated sequence** (optional, later): frames per day → video.

## 6. Priority order (for the visualization focus)

1. Per-device **glyph grid** (metrics + people graph) — cheap, glyph-friendly.
2. **OD glyphs** with baseline-vs-restriction comparison.
3. Day-over-day **H3 density deltas** + concentration index.
4. **Stay-at-home index** time series (most policy-relevant single number).
5. District-level OD + corridor change.

## 7. Caveats (bake into every viz)

- **Coverage ramp-up** 23–25 Oct: normalize by active devices or annotate.
- **Male-skewed, non-representative panel** (~3.4:1): stratify, don't claim
  population totals.
- **Legacy parquet ≠ raw CSV** (slight daily differences): raw CSV is the
  source of truth.
- ~~Smoke-test caveat~~ `data/processed/` now holds **full-window** outputs
  (all 292.2M pings, via `scripts/profile_full.py`, 2026-08-12) — the 500k
  smoke-test caveat no longer applies. Still: raw volume is coverage-dominated
  (Nov 2021 ≈ 100× Apr 2022); use coverage-normalised indices.

## 8. Milestones

- [x] Pipeline: ingest → parquet → H3 grid → OD → metrics (all cached).
- [x] Baseline window + % change tables (`metrics.mobility_index`,
      `scripts/compute_metrics.py --baseline-days N`; incl. by-regency variant).
- [x] OD enrichment: flow distance, corridor change, district-level OD, net
      flows (`od.py` + `scripts/prepare_spatial.py --people ...`).
- [x] Contact / meeting index (`contacts.py` + `scripts/compute_contacts.py`).
- [x] Concentration index (Gini/HHI per day, `spatial.py`).
- [x] Ingest Oct 2021 + regenerate all `data/processed/` outputs on full data
      (`scripts/run_all.py`).
- [x] Ingest **all** remaining CSVs (through Jun 2022) + full-window profile
      (`scripts/profile_full.py`, 9 months, 292.2M pings — `FINDINGS.md` §9).
- [ ] Glyph library integration: metrics + OD data contracts.
- [ ] PPKM/case-data overlay + mobility↔cases correlation.
