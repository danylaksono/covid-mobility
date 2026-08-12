/* UGM Mobility — interactive trace inspector (MapLibre GL JS).
   Loads the GeoJSON exported by scripts/export_traces_web.py and lets you
   toggle devices, click points for time/speed, and animate movement.

   Data model (traces.geojson) is a set of SEGMENT features:
     - kind "move": consecutive pings with short time gaps (solid line)
     - kind "gap" : the jump between two bursts (long time gap, dashed line)
   so long sampling gaps are visually distinct from real movement.
*/

const LAYER = (kind, i) => `${kind}-${i}`; // line-0, gap-0, pts-0, mark-0

const state = {
  segments: [],         // trace segment features (one+ per device)
  deviceList: [],       // unique device ids (order defines layer indices)
  deviceColor: {},      // deviceId -> color
  pointsByDevice: {},   // deviceId -> [point features] (sorted by tsec)
  allTsec: [],          // sorted unique point times (seconds since midnight)
  visible: {},          // deviceId -> bool
  playing: false,
  timer: null,
};

window.addEventListener("load", init);

async function init() {
  const [villages, traces, points] = await Promise.all([
    fetchJSON("data/diy_villages.geojson"),
    fetchJSON("data/traces.geojson"),
    fetchJSON("data/points.geojson"),
  ]);

  const map = new maplibregl.Map({
    container: "map",
    style: {
      version: 8,
      glyphs: "https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf",
      sources: {
        basemap: {
          type: "raster",
          tiles: ["https://basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png"],
          tileSize: 256, attribution: "© OpenStreetMap © CARTO",
        },
      },
      layers: [{ id: "basemap", type: "raster", source: "basemap" }],
    },
    center: [110.45, -7.82],
    zoom: 9,
  });

  window.map = map; // expose for debugging / tests

  map.on("load", () => {
    // village boundaries (context)
    map.addSource("villages", { type: "geojson", data: villages });
    map.addLayer({ id: "village-fill", type: "fill", source: "villages",
      paint: { "fill-color": "#f2ecdf", "fill-opacity": 0.35 } });
    map.addLayer({ id: "village-line", type: "line", source: "villages",
      paint: { "line-color": "#9a9a9a", "line-width": 0.7, "line-opacity": 0.7 } });

    // group data by device
    state.segments = traces.features;
    for (const f of points.features) {
      const id = f.properties.device;
      (state.pointsByDevice[id] = state.pointsByDevice[id] || []).push(f);
    }
    for (const id in state.pointsByDevice) {
      state.pointsByDevice[id].sort((a, b) => a.properties.tsec - b.properties.tsec);
    }
    const ids = new Set();
    for (const f of state.segments) ids.add(f.properties.device);
    state.deviceList = [...ids];
    for (const f of state.segments) state.deviceColor[f.properties.device] = f.properties.color;

    const tset = new Set();
    for (const id in state.pointsByDevice) {
      state.pointsByDevice[id].forEach((p) => tset.add(p.properties.tsec));
    }
    state.allTsec = [...tset].sort((a, b) => a - b);

    // per-device layers + toggles
    state.deviceList.forEach((id, i) => {
      const color = state.deviceColor[id];
      const segs = { type: "FeatureCollection",
                     features: state.segments.filter((f) => f.properties.device === id) };
      map.addSource(LAYER("src", i), { type: "geojson", data: segs });

      map.addLayer({ id: LAYER("line", i), type: "line", source: LAYER("src", i),
        layout: { "line-cap": "round", "line-join": "round" },
        filter: ["==", ["get", "kind"], "move"],
        paint: { "line-color": color, "line-width": 2.5 } });
      map.addLayer({ id: LAYER("gap", i), type: "line", source: LAYER("src", i),
        layout: { "line-cap": "round", "line-join": "round" },
        filter: ["==", ["get", "kind"], "gap"],
        paint: { "line-color": color, "line-width": 1.6, "line-opacity": 0.75,
                 "line-dasharray": [5, 3] } });
      // duration label on long sampling gaps (e.g. "+2h 05m")
      map.addLayer({ id: LAYER("glabel", i), type: "symbol", source: LAYER("src", i),
        layout: { "symbol-placement": "line", "text-field": ["get", "gap_label"],
                  "text-size": 10, "text-offset": [0, 0.9], "text-allow-overlap": false },
        filter: ["all", ["==", ["get", "kind"], "gap"],
                 ["!=", ["get", "gap_label"], ""]],
        paint: { "text-color": color, "text-halo-color": "#fff",
                 "text-halo-width": 1.2 } });

      const pts = { type: "FeatureCollection", features: state.pointsByDevice[id] || [] };
      map.addSource(LAYER("pts", i), { type: "geojson", data: pts });
      map.addLayer({ id: LAYER("pts", i), type: "circle", source: LAYER("pts", i),
        paint: { "circle-color": color, "circle-radius": 5,
                 "circle-stroke-color": "#fff", "circle-stroke-width": 1 } });

      map.addSource(LAYER("mark", i), { type: "geojson", data: emptyFC() });
      map.addLayer({ id: LAYER("mark", i), type: "circle", source: LAYER("mark", i),
        layout: { visibility: "none" },
        paint: { "circle-color": "#111", "circle-radius": 8,
                 "circle-stroke-color": color, "circle-stroke-width": 3 } });

      state.visible[id] = true;
      addToggle(i, id, color);
      map.on("click", LAYER("pts", i), (e) => showPopup(e, id));
    });

    // slider / play
    const slider = document.getElementById("slider");
    slider.addEventListener("input", () => setTime(map, Number(slider.value) / 1000));
    document.getElementById("play").addEventListener("click", () => togglePlay(map));
    document.getElementById("fit").addEventListener("click", () => fitAll(map));

    document.getElementById("day").textContent = "Oct 2021";
    document.getElementById("filter-note").textContent = "120 km/h · dashed = gap > 30 min";
    fitAll(map);
  });
}

function addToggle(i, id, color) {
  const pts = state.pointsByDevice[id] || [];
  const n = pts.length;
  const t0 = pts.length ? pts[0].properties.time : "";
  const t1 = pts.length ? pts[pts.length - 1].properties.time : "";
  const box = document.createElement("div");
  box.className = "dev";
  box.innerHTML =
    `<input type="checkbox" id="cb-${i}" checked>` +
    `<span class="swatch" style="background:${color}"></span>` +
    `<label for="cb-${i}">${shortId(id)}<br>` +
    `<span class="meta">${n} pings · ${t0}–${t1}</span></label>`;
  const cb = box.querySelector("input");
  cb.addEventListener("change", () => toggleDevice(i, id, cb.checked));
  document.getElementById("devices").appendChild(box);
}

function toggleDevice(i, id, on) {
  state.visible[id] = on;
  for (const kind of ["line", "gap", "glabel", "pts", "mark"]) {
    map.setLayoutProperty(LAYER(kind, i), "visibility", on ? "visible" : "none");
  }
}

function showPopup(e, device) {
  const p = e.features[0].properties;
  const color = state.deviceColor[device];
  const [lon, lat] = e.lngLat.toArray();
  const pts = state.pointsByDevice[device] || [];
  const near = pts.filter((q) =>
    Math.abs(q.geometry.coordinates[0] - lon) < 0.001 &&
    Math.abs(q.geometry.coordinates[1] - lat) < 0.001);
  let burst = "";
  if (near.length > 1) {
    burst = `<br><b>${near.length} pings here</b> · ${near[0].properties.time}–${near[near.length - 1].properties.time}`;
  }
  new maplibregl.Popup({ offset: 12 })
    .setLngLat(e.lngLat)
    .setHTML(
      `<span class="sw" style="background:${color}"></span><b>${shortId(device)}</b>` +
      `<br>time: <b>${p.time}</b> (ping ${p.idx}/${pts.length})` +
      `<br>speed to prev: <b>${p.speed_kmh} km/h</b>` + burst +
      `<br>${e.lngLat.lng.toFixed(5)}, ${e.lngLat.lat.toFixed(5)}`)
    .addTo(map);
}

// ---- animation ------------------------------------------------------------//
function setTime(map, frac) {
  const target = state.allTsec.length
    ? state.allTsec[Math.min(state.allTsec.length - 1, Math.round(frac * (state.allTsec.length - 1)))]
    : 0;
  document.getElementById("clock").textContent = fmtSec(target);
  state.deviceList.forEach((id, i) => {
    if (!state.visible[id]) return;
    const pts = state.pointsByDevice[id] || [];
    let best = null;
    for (const p of pts) { if (p.properties.tsec <= target) best = p; else break; }
    map.getSource(LAYER("mark", i)).setData(best ? best : emptyFC());
    map.setLayoutProperty(LAYER("mark", i), "visibility", best ? "visible" : "none");
  });
}

function togglePlay(map) {
  const btn = document.getElementById("play");
  if (state.playing) {
    state.playing = false; btn.textContent = "▶ Play";
    clearInterval(state.timer);
    return;
  }
  state.playing = true; btn.textContent = "⏸ Pause";
  const slider = document.getElementById("slider");
  slider.value = 0;
  const step = Math.max(1, Math.round(1000 / 120));
  state.timer = setInterval(() => {
    const v = Number(slider.value) + step;
    if (v >= 1000) { slider.value = 0; setTime(map, 0); return; }
    slider.value = v;
    setTime(map, v / 1000);
  }, 40);
}

function fitAll(map) {
  const bounds = new maplibregl.LngLatBounds();
  let any = false;
  for (const f of state.segments) {
    for (const [lon, lat] of f.geometry.coordinates) { bounds.extend([lon, lat]); any = true; }
  }
  if (any) map.fitBounds(bounds, { padding: 40, maxZoom: 14 });
}

// ---- helpers --------------------------------------------------------------//
function shortId(id) { return id.slice(0, 8) + "…"; }
function fmtSec(t) {
  const h = String(Math.floor(t / 3600)).padStart(2, "0");
  const m = String(Math.floor((t % 3600) / 60)).padStart(2, "0");
  const s = String(t % 60).padStart(2, "0");
  return `${h}:${m}:${s}`;
}
function emptyFC() { return { type: "FeatureCollection", features: [] }; }
async function fetchJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`fetch ${url}: ${r.status}`);
  return r.json();
}
