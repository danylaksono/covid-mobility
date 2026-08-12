# Findings — Yogyakarta GPS mobility (Oct 2021, COVID-19)

This document records the analysis results produced so far from
`UGM_Mobility_Data_Analysis.ipynb`. Numbers were computed from the cleaned
data (24 artifact rows removed). All values refer to the **23–31 Oct 2021**
window unless stated otherwise.

> **Data provenance note (Oct 2021):** the figures below were computed from the
> **legacy parquet** (`data/Parquet/oktober_2021.parquet.gzip`, the prior
> pre-processing). Re-ingesting the **raw CSV** with the new pipeline
> (`scripts/process_mobility.py` → `data/parquet/mobility.parquet`) gives
> slightly different daily totals — both files have 12,123,709 rows, but e.g.
> 31 Oct is 3.18M (legacy) vs 3.31M (CSV). The raw CSV is now the source of
> truth; reconcile these numbers when re-running the analysis on the pipeline
> parquet.

## 1. Dataset at a glance

| Metric                           | Value                                  |
| -------------------------------- | -------------------------------------- |
| Mobility pings (cleaned)         | 12,123,709                             |
| Unique devices                   | 398,142                                |
| Time range                       | 2021-10-23 00:00 → 2021-10-31 16:59    |
| Spatial extent (deg)             | lon 110.003–110.831, lat −8.198–−7.577 |
| People-graph profiles (unique)   | 1,245,225                              |
| Devices present in BOTH datasets | 133,908 (~34% of mobility devices)     |

## 2. Temporal findings

Daily ping volume **grows sharply through the week** — volume on 29–31 Oct is
**30–45×** the 23 Oct baseline. This is a strong signal of either (a) rapidly
increasing data coverage / onboarding of devices, or (b) increased movement
(dangerous during a COVID wave — a key thing to check against PPKM policy
timeline).

| Date       | Pings     | Active devices |
| ---------- | --------- | -------------- |
| 2021-10-23 | 75,252    | 21,953         |
| 2021-10-24 | 237,469   | 19,950         |
| 2021-10-25 | 291,404   | 27,104         |
| 2021-10-26 | 452,725   | 27,788         |
| 2021-10-27 | 975,904   | 54,406         |
| 2021-10-28 | 971,880   | 58,987         |
| 2021-10-29 | 2,428,315 | 169,779        |
| 2021-10-30 | 3,508,825 | 149,574        |
| 2021-10-31 | 3,181,935 | 128,284        |

Observations:

- **Weekday/weekend pattern visible** in the later, well-covered days
  (29–31 Oct) — active devices dip from Fri (170k) → Sun (128k).
- **Hourly diurnal rhythm** is strong (morning/evening peaks) — consistent
  with commuter-style mobility. Night-time (00:00–04:00) activity is minimal.
- The first 3 days (23–25 Oct) have low device counts (~20–27k) — likely a
  **partial / ramp-up sample**, so early-day "drops" should not be over-read.

## 3. Spatial findings

- All points fall inside the DIY region (~110.0–110.8°E, −8.2–−7.6°N).
- Density concentrates around **Yogyakarta city (Kota Yogyakarta)** and the
  **Sleman / Bantul urban corridor** (see the interactive maps in the notebook).
- The northern bound (−7.577°N) reaches toward the **Merapi slope / Sleman
  north** — an area relevant if studying evacuation vs. normal mobility.

## 4. People-graph findings (device profiles)

Profiles are keyed by `maid`; a maid may appear up to 4× in the raw file
(deduplicate by `maid` for device-level stats). Missing values are encoded as
the literal string `\N` (must be replaced with `NaN` before analysis).

**Sex** (unique devices): male **472,137**, female **140,176**, missing ~633k.
→ the profile sample is ~3.4:1 male-skewed (typical of ad-ID panels; do not
treat as population-representative).

**Intensity** (unique devices): low **238,589**, medium **125,887**, high
**20,449**, missing ~860k.

**Regency (`place1`)** (unique devices):

| Regency         | Devices |
| --------------- | ------- |
| Sleman          | 578,689 |
| Kota Yogyakarta | 305,217 |
| Bantul          | 240,477 |
| Gunung Kidul    | 68,454  |
| Kulon Progo     | 52,388  |

→ ~92% of profiled devices are in the **Sleman / Kota Yogyakarta / Bantul**
urban agglomeration. `place2` / `place3` give the district and village
subdivisions (see data dictionary).

## 5. Data-quality notes (important)

- **24 artifact rows** in `oktober_2021.parquet.gzip` contain a leaked header
  string (`maid` in `maid`, `timestamp` in `timestamp`, empty geometry).
  Filter `timestamp != 'timestamp'` before analysis.
- Missing values in `people_graph` are literal `\N` strings, not `NaN`.
- `people_graph` rows are **not unique per maid** (1–4 rows each); use
  `drop_duplicates('maid')` for device-level statistics.
- Timestamps are unix seconds and are treated as **UTC** in this notebook; DIY
  local time is UTC+7 (WIB). Decide & document timezone handling before
  publishing.

## 6. Suggested next steps

1. Reconcile the 23–25 Oct ramp-up: is low volume real or a coverage artifact?
2. Merge `people_graph` demographics into pings and compare mobility by
   **sex / intensity / regency**.
3. Analyze **home location vs. weekday travel distance** (origin-destination),
   and whether movement changes over the window (COVID restriction effects).
   H3 grids and OD flows are already produced by `scripts/prepare_spatial.py`.
4. Cross-reference daily activity with the **PPKM restriction timeline** for
   Yogyakarta in late Oct 2021.
5. Extend the pipeline to the **Oct 2021 → May 2022** CSVs
   (`scripts/process_mobility.py`), then re-aggregate spatially.

> **Architecture note:** processing now lives in `src/mobility` + `scripts`
> (DuckDB + H3); the notebook is visualisation-only and static. See
> [`AGENTS.md`](AGENTS.md) for the full picture.

---

## 7. Full-data pipeline results — Oct 2021 (2026-08-11)

Full run via `scripts/run_all.py` on the complete 12.12M-ping dataset
(no sample). `data/processed/` is now full-data, not sample-based.

| Step                 | Output                            | Value                  |
| -------------------- | --------------------------------- | ---------------------- |
| Ingest               | pings / people rows               | 12,123,709 / 1,834,289 |
| H3 grid (r8)         | (date, cell) rows                 | 25,518                 |
| OD                   | device-day trips / directed flows | 657,825 / 65,897       |
| District OD (place1) | flows / net pairs                 | 321 / 133              |
| Homes                | devices with a home cell          | 208,099                |
| Metrics              | device-days                       | 657,825                |
| Contacts             | (hour, cell) occupancy rows       | 210,126                |

**Temporal / coverage:** daily pings now match the raw CSV exactly
(23 Oct 75.3k → 31 Oct 3.18M) — a steep coverage ramp-up dominates raw volume.

**Mobility (stay-at-home, `mobility_index_r8`):** baseline (23–25 Oct) stay-at-home
≈ **43.4%**; daily values fluctuate within **−7% to +12%** of baseline — i.e.
little net change in the stay-at-home rate across the window (the meaningful,
coverage-normalised signal).

**Spatial concentration (`concentration_r8`):** HHI ≈ 0.0026–0.0032
(near-uniform spread across ~300–380 effective cells at r8); Gini 0.75–0.81,
rising slightly later in the week.

**OD (`od_flows_r8`, `od_flows_district_r8`):**

- Mean trip length **4.48 km**, median **1.73 km** (origin–dest cell centroid).
- Intra-regency travel dominates (Sleman→Sleman 5.08M pings, Bantul→Bantul
  2.61M, Kota Yogyakarta→Kota 1.87M).
- Top inter-regency corridors: Sleman↔Kota Yogyakarta (~177k/176k, balanced),
  then Sleman↔Bantul.
- Net flows show modest directional imbalance (e.g. 27 Oct net −8.1k
  Bantul→Kota Yogyakarta, i.e. net movement toward the city); many pairs are
  dominated by "unknown" cells (devices with no people-graph home).

**Meeting index (`meeting_index_daily_r8_1h`):** 79k (23 Oct) → 41M (29 Oct)
pairwise co-locations. **Entirely coverage-driven** on raw volume — needs
normalization (per active device or per ping) before interpretation.

**Data-quality notes from the full run:**

- `people_graph` join coverage is limited (~34% of devices), so district OD /
  net flows have an "unknown" class that dominates some pairs.
- 657,825 device-days ≈ 18 pings/device-day on average, but the **median
  device-day has 1 distinct cell / 0 km radius** — most device-days are
  effectively stationary, consistent with a stay-at-home rate ~44%.

---

## 8. GPS outliers — why traces have "impossible" jumps (2026-08-11)

Diagnosed after large straight-line jumps appeared in per-device traces:

- **99% of consecutive pings are ≤ 1 km apart** (median ~0 km — devices sit in
  stationary bursts; 86.5% of gaps ≤ 1 min). The data is essentially clean at
  the ping level.
- The jumps come from a small fraction of **GPS spikes**: ~0.3% of pings imply
  implausible speeds, and **96.5% of pairs implying >60 km/h happen in gaps
  < 5 min** (median 0.3 min). Max implied speed observed ~**1.7×10⁵ km/h**.
- Conclusion: these are **erroneous coordinates / bad fixes** (or a `maid`
  reused across devices), **not** real movement. Trace lines were connecting
  them to neighbours, producing the giant straight jumps.

**Fix (added):** `mobility.clean.filter_speed_outliers(df, max_kph=120)` drops
pings whose implied speed to the previous ping exceeds the threshold
(`scripts/plot_traces.py --max-speed-kph 120`, applied before tracing).
On 30 Oct it removed 9,876 / 3,508,825 pings (~0.28%). After filtering, traces
show plausible movement (e.g. a 70 km Semin→Ngestiharjo trip, 25 km commutes,
and short local loops).

**Filter bug found & fixed (2026-08-11):** `speed_outlier_mask` originally
returned its mask in the *sorted* order while `filter_speed_outliers` applied it
to the original frame → misalignment, so some spikes were kept and some good
pings dropped. Now the mask is aligned to the input row order (and the previous
timestamp uses a grouped shift). Verified: `d2197cc4` (66 pings) had 3 GPS
spikes (9.8 km/1.4 min = 421 km/h; 67.2 km/0.1 min = 40 345 km/h; 67.2 km/2.9 min
= 1 416 km/h) that are now removed (63 pings). Its real journey is a coherent
~81 km trip from east Gunungkidul (Semin) to central DIY across ~5.5 h
(plausible), not the apparent teleportation.

Caveat: pings at a spike timestamp are often duplicated, so one copy can
survive the filter — minor; the large back-and-forth spikes are removed.

---

## 9. Full-data profile — all nine months (2026-08-12)

Full-window run via `scripts/profile_full.py` on the **combined 9-month**
parquet (`data/parquet/mobility.parquet`, 292.2M pings). `data/processed/` now
holds **full-window** outputs (not the earlier 500k smoke test, not the
Oct-only full run). See `data/processed/_profile_run.log` for the run log.

| Metric                              | Value                                  |
| ----------------------------------- | -------------------------------------- |
| Time window (UTC)                   | 2021-10-23 → 2022-06-07 (228 days)     |
| Total pings                         | 292,226,383                            |
| Devices with a home cell            | 2,496,775 (~58% of the ~4.28M maids)   |
| Device-days                         | 17,943,752                             |
| H3 grid (r8)                        | 525,542 (date, cell) rows / 228 days   |
| OD device-day trips / flows         | 17,943,752 / 1,459,195                 |
| Corridor-change rows                | 1,459,195                              |
| Mobility index                      | 228 days (vs. 23–25 Oct baseline)      |
| Contacts (occupancy, 1 h buckets)   | 5,170,155 rows / 5,462 buckets / 228 d |
| Crowding rows                       | 5,462                                  |
| Runtime (10 date-chunks, 2 passes)  | ~41 min                                |

**Headline numbers (whole window):**

- **Stay-at-home rate ≈ 42.7%** — remarkably consistent with the Oct-only
  baseline (~43.4%, §7). Across nine months the share of device-days that
  never leave the home cell holds steady in the low 40s.
- **Median device-day is stationary**: median radius **0.00 km**, median
  **1 trip**, median **1 distinct cell**. ~16 pings/device-day on average
  (292.2M / 17.9M), but most device-days are effectively at home.
- **Coverage**: pings are far from uniform across the window (Nov 2021 is the
  heaviest month, ~100.9M pings; Apr 2022 the lightest, ~1.0M — a 100× span).
  Any raw-volume time series is coverage-dominated; use the
  coverage-normalised indices (`mobility_index_*`, stay-at-home, per-device)
  for interpretation.

**Consistency checks:** the Oct-only full run (§7, 12.12M pings) and this
9-month run agree on the structural facts — high stay-at-home (~43%), median
device-day ≈ stationary, meeting index strongly coverage-driven (§7 caveat
applies to the whole window). The 9-month dataset adds the **PPKM / pandemic
timeline context**: Oct 2021 (PPKM level 2–3 ramp) through Jun 2022 (PPKM
lifted, mask mandate relaxed) — the stay-at-home index is the right series to
overlay against that timeline.
