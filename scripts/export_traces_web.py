"""Export sample traces + DIY boundaries as GeoJSON for the MapLibre web viewer.

Reads the prepared mobility parquet, speed-filters GPS spikes, picks a few
sample devices (mix of long-distance / commuters / local), and writes the
files that ``web/index.html`` loads:

    web/data/diy_villages.geojson   simplified village boundaries (basemap)
    web/data/traces.geojson         one LineString per sampled device
    web/data/points.geojson         one Point per ping (time + speed for popups)

Usage
-----
    python scripts/export_traces_web.py --day 2021-10-30 --n 5 --pick mix

Then serve the folder (must use http://, not file://, for fetch()):
    python -m http.server 8000 --directory web
    # open http://localhost:8000
"""

from __future__ import annotations

import argparse
import json
import sys
import time as _time
from pathlib import Path

import geopandas as gpd
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from mobility import clean, config, io  # noqa: E402
from plot_traces import TRACE_COLORS, _pick_maids, _pick_maids_mix  # noqa: E402

WEB_DIR = Path(__file__).resolve().parents[1] / "web" / "data"


def _line_features(device: str, one: pd.DataFrame, color: str,
                   gap_split_min: float = 30.0,
                   label_min_min: float = 60.0) -> list[dict]:
    """Split a device's time-ordered pings into GeoJSON line segments.

    Consecutive pings with a gap <= ``gap_split_min`` minutes belong to one
    "move" segment (solid on the map). The jump between two bursts (gap >
    threshold) is emitted as a 2-point "gap" segment (dashed on the map), so
    long sampling gaps are visually distinct from real movement. Gap segments
    carry a human-readable ``gap_label`` (e.g. "+2h 05m") when the gap is at
    least ``label_min_min`` minutes.
    """
    one = one.sort_values("timestamp").reset_index(drop=True)
    lon = one["longitude"].to_numpy()
    lat = one["latitude"].to_numpy()
    ts = one["timestamp"].astype("int64").to_numpy()
    gaps_min = (ts[1:] - ts[:-1]) / 60.0

    def seg(a, b, kind, gap_label=""):
        return {
            "type": "Feature",
            "properties": {"device": device, "color": color, "kind": kind,
                           "n": b - a + 1, "gap_label": gap_label},
            "geometry": {"type": "LineString",
                         "coordinates": [[round(float(lon[i]), 6),
                                          round(float(lat[i]), 6)]
                                         for i in range(a, b + 1)]},
        }

    feats = []
    start = 0
    for i in range(1, len(one)):
        if gaps_min[i - 1] > gap_split_min:
            if i - 1 - start >= 1:          # real segment (>= 2 points)
                feats.append(seg(start, i - 1, "move"))
            g = gaps_min[i - 1]
            label = "" if g < label_min_min else f"+{int(g // 60)}h {int(g % 60):02d}m"
            feats.append(seg(i - 1, i, "gap", gap_label=label))  # the big jump
            start = i
    if len(one) - 1 - start >= 1:
        feats.append(seg(start, len(one) - 1, "move"))
    return feats


def _point_features(device: str, one: pd.DataFrame) -> list[dict]:
    one = one.sort_values("timestamp").reset_index(drop=True)
    lon = one["longitude"].to_numpy()
    lat = one["latitude"].to_numpy()
    ts = one["timestamp"].astype("int64").to_numpy()
    # implied speed to the previous ping (km/h) for popups
    import numpy as np
    dist = _haversine(lon[1:], lat[1:], lon[:-1], lat[:-1])
    dt = (ts[1:] - ts[:-1]) / 3600.0
    with np.errstate(divide="ignore", invalid="ignore"):
        speed = np.where(dt > 0, dist / dt, 0.0)
    speed = np.nan_to_num(speed, nan=0.0, posinf=0.0, neginf=0.0)
    feats = []
    for i in range(len(one)):
        spd = round(float(speed[i - 1]), 1) if i > 0 else 0.0
        feats.append({
            "type": "Feature",
            "properties": {
                "device": device,
                "idx": i,
                "time": one["datetime"].iloc[i].strftime("%H:%M:%S"),
                "tsec": int(ts[i]) % 86400,
                "speed_kmh": spd,
            },
            "geometry": {"type": "Point", "coordinates": [round(lon[i], 6), round(lat[i], 6)]},
        })
    return feats


def _haversine(lon1, lat1, lon2, lat2):
    import numpy as np
    R = 6371.0
    lon1, lat1, lon2, lat2 = map(np.radians, [lon1, lat1, lon2, lat2])
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 2 * R * np.arcsin(np.clip(np.sqrt(a), 0, 1))


def export(day: str, n: int, pick: str, max_speed_kph: float,
           boundaries: Path) -> None:
    WEB_DIR.mkdir(parents=True, exist_ok=True)

    # ---- boundaries (simplified for the web) -----------------------------#
    villages = gpd.read_file(boundaries)
    simp = villages[["NAMOBJ", "geometry"]].copy()
    simp["geometry"] = simp.geometry.simplify(0.0008, preserve_topology=True)
    simp = simp.drop(columns=["NAMOBJ"])
    simp_path = WEB_DIR / "diy_villages.geojson"
    simp.to_file(simp_path, driver="GeoJSON")
    print(f"  villages -> {simp_path.name} "
          f"({len(simp)} polys, {simp_path.stat().st_size/1e6:.1f} MB)")

    # ---- sample devices ---------------------------------------------------#
    print("loading mobility ...")
    t0 = _time.perf_counter()
    df = io.load_mobility(config.MOBILITY_PARQUET)
    d = clean.filter_speed_outliers(
        df[df["date"] == pd.Timestamp(day)].copy(), max_kph=max_speed_kph)
    print(f"  {len(d):,} pings on {day} in {_time.perf_counter()-t0:.1f}s")

    chosen = (_pick_maids_mix(d, n=n, min_pings=10) if pick == "mix"
              else _pick_maids(d, n=n, min_pings=10))
    print(f"  sampling {len(chosen)} devices ({pick})")

    # ---- traces + points --------------------------------------------------#
    line_feats, point_feats = [], []
    for i, maid in enumerate(chosen):
        one = d[d["maid"] == maid]
        color = TRACE_COLORS[i % len(TRACE_COLORS)]
        line_feats.extend(_line_features(maid, one, color))
        point_feats.extend(_point_features(maid, one))
        print(f"    {maid[:10]}…  {len(one)} pings")

    traces_path = WEB_DIR / "traces.geojson"
    traces_path.write_text(json.dumps({"type": "FeatureCollection", "features": line_feats}))
    points_path = WEB_DIR / "points.geojson"
    points_path.write_text(json.dumps({"type": "FeatureCollection", "features": point_feats}))
    print(f"  traces  -> {traces_path.name} ({traces_path.stat().st_size/1e6:.2f} MB)")
    print(f"  points  -> {points_path.name} ({points_path.stat().st_size/1e6:.2f} MB)")
    print("\nserve with:  python -m http.server 8000 --directory web")


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--day", default="2021-10-30")
    ap.add_argument("--n", type=int, default=8)
    ap.add_argument("--pick", default="mix", choices=["top", "mix"])
    ap.add_argument("--max-speed-kph", type=float, default=120.0)
    ap.add_argument("--boundaries", default="data/geo/batas_desa_diy.gpkg")
    args = ap.parse_args()

    export(args.day, args.n, args.pick, args.max_speed_kph,
           Path(args.boundaries))


if __name__ == "__main__":
    main()
