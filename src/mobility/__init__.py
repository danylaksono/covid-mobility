"""ugm-mobility: processing pipeline for the UGM Yogyakarta GPS mobility data.

Separation of concerns
----------------------
- ``src/mobility/``  : reusable, tested processing code (duckdb + h3 based).
- ``scripts/``       : one-shot pipeline steps (CSV -> parquet -> aggregates).
- ``notebooks/``     : *thin* notebooks that only load prepared data and
  visualise (no heavy processing inline).

The heavy lifting (large CSVs, spatial aggregation, OD construction) is done by
the scripts / package, never in a notebook.
"""

__version__ = "0.1.0"
