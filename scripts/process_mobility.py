"""Convert raw mobility / people-graph CSVs into cleaned Parquet files.

DuckDB does the heavy lifting (streaming, parallel), so 100 MB – 1 GB CSVs are
handled without loading them into Python.

Supports multiple mobility CSVs (one per month, Oct 2021 … Jun 2022) either via
a glob pattern (``--mobility``) or, for the current ``data/raw`` layout where
each month lives in its own folder, via ``--raw-dir`` which recurses and groups
files by month.

- Glob mode: each input becomes ``<out_dir>/mobility_<stem>.parquet``; if more
  than one file matches, a combined ``<out_dir>/mobility.parquet`` is also built.
- Tree mode (``--raw-dir``): every ``*.csv`` under the dir is discovered
  (excluding ``people_graph.csv`` / ``mpd_sample_small.csv``), byte-identical
  duplicates are dropped, multi-part months (e.g. ``November2021_part1..7``)
  are combined, and one ``<out_dir>/mobility_<MonthYear>.parquet`` is written
  per month, plus a combined ``<out_dir>/mobility.parquet``. Months whose
  parquet is already newer than all their source CSVs are **skipped**, so
  re-runs only ingest new/changed months; pass ``--force`` to re-ingest all.

Usage
-----
    # tree mode (current layout: month folders, some months in parts)
    python scripts/process_mobility.py \
        --raw-dir data/raw \
        --people  data/raw/people_graph.csv \
        --out     data/parquet

    # legacy glob mode
    python scripts/process_mobility.py \
        --mobility "data/raw/*.csv" \
        --people  data/raw/people_graph.csv \
        --out     data/parquet

    # people graph only
    python scripts/process_mobility.py --people data/raw/people_graph.csv --out data/parquet
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mobility import config, io  # noqa: E402


def convert_mobility_glob(glob: str, out_dir: Path,
                          exclude_stems: tuple[str, ...] = ("people_graph",)) -> list[Path]:
    """Convert all CSVs matching ``glob`` that are mobility files.

    ``exclude_stems`` lets the run skip non-mobility CSVs that live in the
    same folder (e.g. the headerless ``people_graph.csv``).
    """
    files = sorted(Path().glob(glob))
    if not files:
        files = sorted(Path(glob).parent.glob(Path(glob).name))
    files = [f for f in files if f.is_file() and f.stem not in exclude_stems]
    if not files:
        raise SystemExit(f"no mobility CSV files matched: {glob!r}")

    out_dir.mkdir(parents=True, exist_ok=True)
    outputs = []
    for i, f in enumerate(files, 1):
        t0 = time.perf_counter()
        out = out_dir / f"mobility_{f.stem}.parquet"
        io.mobility_csv_to_parquet(f, out)
        n = _row_count(out)
        print(f"[{i}/{len(files)}] {f.name} -> {out.name} "
              f"({n:,} rows, {time.perf_counter()-t0:.1f}s)")
        outputs.append(out)

    # Always emit a canonical `mobility.parquet` for downstream consumers.
    combined = out_dir / "mobility.parquet"
    if len(outputs) == 1:
        import shutil
        shutil.copyfile(outputs[0], combined)
    else:
        t0 = time.perf_counter()
        _concat_parquet(outputs, combined)
        print(f"combined -> {combined.name} "
              f"({_row_count(combined):,} rows, {time.perf_counter()-t0:.1f}s)")
    return outputs


def convert_people(csv_path: str | Path, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "people.parquet"
    t0 = time.perf_counter()
    io.people_csv_to_parquet(csv_path, out)
    print(f"people {Path(csv_path).name} -> {out.name} "
          f"({_row_count(out):,} rows, {time.perf_counter()-t0:.1f}s)")
    return out


# --------------------------------------------------------------------------- #
# Tree mode: recurse over data/raw, group multi-part months, dedupe, ingest
# --------------------------------------------------------------------------- #

# Suffix used when a month is split across several CSVs, e.g. part1..part7.
_PART_RE = re.compile(r"^(?P<base>.+)_part(?P<num>\d+)$", re.IGNORECASE)

# Non-mobility CSVs that live in data/raw and must never be ingested as mobility.
_NON_MOBILITY_STEMS = ("people_graph", "mpd_sample_small")


def month_key(stem: str) -> str:
    """Map a CSV stem to its month group, e.g. 'November2021_part2' -> 'November2021'."""
    m = _PART_RE.match(stem)
    return m.group("base") if m else stem


def _content_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _dedupe_identical(files: list[Path]) -> list[Path]:
    """Drop exact-duplicate CSVs (same content), keeping the first occurrence.

    Only files sharing a byte size are hashed (cheap pre-filter): the only known
    duplicates are e.g. ``Oktober2021.csv`` copied at ``data/raw`` root and again
    in its month folder.
    """
    by_size: dict[int, list[Path]] = {}
    for f in files:
        by_size.setdefault(f.stat().st_size, []).append(f)
    keep: list[Path] = []
    for _size, group in by_size.items():
        if len(group) == 1:
            keep.append(group[0])
            continue
        seen: set[str] = set()
        for f in sorted(group):
            h = _content_hash(f)
            if h not in seen:
                seen.add(h)
                keep.append(f)
    return sorted(keep)


def discover_mobility_files(raw_dir: str | Path) -> list[Path]:
    """Recursively find mobility CSVs under ``raw_dir``, deduped and sorted."""
    raw_dir = Path(raw_dir)
    csvs = [p for p in raw_dir.rglob("*.csv")
            if p.is_file() and p.stem.lower() not in _NON_MOBILITY_STEMS]
    if not csvs:
        raise SystemExit(f"no mobility CSV files found under {raw_dir!r}")
    return _dedupe_identical(csvs)


def _month_parquet_fresh(out: Path, parts: list[Path]) -> bool:
    """True if ``out`` exists, is non-empty, and is newer than every source CSV."""
    if not out.exists() or out.stat().st_size == 0:
        return False
    out_mtime = out.stat().st_mtime
    return all(out_mtime >= p.stat().st_mtime for p in parts)


def convert_mobility_tree(raw_dir: str | Path, out_dir: Path,
                          force: bool = False) -> list[Path]:
    """Ingest every month under ``raw_dir`` into one Parquet each.

    Multi-part months are combined into a single ``mobility_<MonthYear>.parquet``
    and a combined ``mobility.parquet`` is (re)built from all months. Months
    whose parquet is already newer than their source CSVs are skipped unless
    ``force`` is set (so re-running only ingests new/changed months).
    """
    files = discover_mobility_files(raw_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    groups: dict[str, list[Path]] = {}
    for f in files:
        groups.setdefault(month_key(f.stem), []).append(f)

    outputs = []
    for key in sorted(groups):
        parts = sorted(groups[key])
        out = out_dir / f"mobility_{key}.parquet"
        if not force and _month_parquet_fresh(out, parts):
            n = _row_count(out)
            print(f"[{key}] up-to-date, reusing {out.name} ({n:,} rows)")
            outputs.append(out)
            continue
        t0 = time.perf_counter()
        io.mobility_csvs_to_parquet(parts, out)
        n = _row_count(out)
        src = ", ".join(p.name for p in parts)
        print(f"[{key}] {src} -> {out.name} "
              f"({n:,} rows, {time.perf_counter()-t0:.1f}s)")
        outputs.append(out)

    combined = out_dir / "mobility.parquet"
    t0 = time.perf_counter()
    if len(outputs) == 1:
        import shutil
        shutil.copyfile(outputs[0], combined)
    else:
        _concat_parquet(outputs, combined)
    print(f"combined -> {combined.name} "
          f"({_row_count(combined):,} rows, {time.perf_counter()-t0:.1f}s)")
    return outputs


def _row_count(parquet: Path) -> int:
    import duckdb
    with duckdb.connect() as con:
        return con.execute(
            "SELECT count(*) FROM read_parquet(?)", [str(parquet)]).fetchone()[0]


def _concat_parquet(files: list[Path], out: Path) -> None:
    import duckdb
    paths = ", ".join(f"'{f}'" for f in files)
    out_q = str(out).replace("'", "''")
    with duckdb.connect() as con:
        con.execute(
            f"COPY (SELECT * FROM read_parquet([{paths}])) TO '{out_q}' "
            "(FORMAT PARQUET, COMPRESSION ZSTD)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mobility", default=None,
                    help="glob of mobility CSVs (default: none)")
    ap.add_argument("--raw-dir", default=None,
                    help="recursively ingest every month under this dir "
                         "(multi-part months combined; mutually exclusive "
                         "with --mobility)")
    ap.add_argument("--force", action="store_true",
                    help="with --raw-dir, re-ingest every month even if its "
                         "parquet is already up to date")
    ap.add_argument("--people", default=None,
                    help="path to people-graph CSV (default: none)")
    ap.add_argument("--out", default=str(config.PARQUET_DIR), help="output dir")
    args = ap.parse_args()

    if not args.mobility and not args.raw_dir and not args.people:
        ap.error("provide at least one of --mobility, --raw-dir or --people")

    out_dir = Path(args.out)
    if args.raw_dir:
        convert_mobility_tree(args.raw_dir, out_dir, force=args.force)
    elif args.mobility:
        convert_mobility_glob(args.mobility, out_dir)
    if args.people:
        convert_people(args.people, out_dir)


if __name__ == "__main__":
    main()
