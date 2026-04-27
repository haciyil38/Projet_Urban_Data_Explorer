const API_BASE = "http://localhost:8000";

// ── Carte ──────────────────────────────────────────────────────────────────

const map = new maplibregl.Map({
  container: "map",
  style: "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
  center: [2.3522, 48.8566],
  zoom: 12,
});

map.addControl(new maplibregl.NavigationControl(), "top-left");
map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-left");

// ── Couleurs par catégorie ─────────────────────────────────────────────────

const CATEGORY_COLORS = {
  culturels:    "#7c3aed",
  evenements:   "#0891b2",
  sport:        "#16a34a",
  associations: "#d97706",
};

// ── État ───────────────────────────────────────────────────────────────────

let currentMarker = null;
let currentCircle = null;
let currentRadius = 500;

// ── UI refs ────────────────────────────────────────────────────────────────

const radiusInput  = document.getElementById("radius");
const radiusLabel  = document.getElementById("radius-label");
const resultDiv    = document.getElementById("result-culture");
const hintDiv      = document.getElementById("hint-culture");
const loadingDiv   = document.getElementById("loading");
const errorDiv     = document.getElementById("error");

const scoreVal     = document.getElementById("score-value");
const dEvt         = document.getElementById("d-evenements");
const dCult        = document.getElementById("d-culturels");
const dSport       = document.getElementById("d-sport");
const dAsso        = document.getElementById("d-associations");
const barEvt       = document.getElementById("bar-evt");
const barCult      = document.getElementById("bar-cult");
const barSport     = document.getElementById("bar-sport");
const barAsso      = document.getElementById("bar-asso");

// ── Rayon ──────────────────────────────────────────────────────────────────

let radiusDebounce = null;

radiusInput.addEventListener("input", () => {
  currentRadius = parseInt(radiusInput.value);
  radiusLabel.textContent = `${currentRadius} m`;
  if (currentMarker) {
    const { lng, lat } = currentMarker.getLngLat();
    updateCircle(lat, lng, currentRadius);
    clearTimeout(radiusDebounce);
    radiusDebounce = setTimeout(() => fetchScore(lat, lng, currentRadius), 400);
  }
});

// ── Clic carte ─────────────────────────────────────────────────────────────

map.on("click", (e) => {
  if (document.getElementById("tab-culture").classList.contains("hidden")) return;
  const { lng, lat } = e.lngLat;
  placeMarker(lat, lng);
  updateCircle(lat, lng, currentRadius);
  fetchScore(lat, lng, currentRadius);
});

// ── Marker ─────────────────────────────────────────────────────────────────

function placeMarker(lat, lng) {
  if (currentMarker) currentMarker.remove();
  currentMarker = new maplibregl.Marker({ color: "#4f46e5" })
    .setLngLat([lng, lat])
    .addTo(map);
}

// ── Cercle de rayon ────────────────────────────────────────────────────────

function updateCircle(lat, lng, radiusM) {
  const geojson = circleGeoJSON(lat, lng, radiusM);

  if (map.getSource("radius-circle")) {
    map.getSource("radius-circle").setData(geojson);
  } else {
    map.addSource("radius-circle", { type: "geojson", data: geojson });
    map.addLayer({
      id: "radius-fill",
      type: "fill",
      source: "radius-circle",
      paint: { "fill-color": "#4f46e5", "fill-opacity": 0.08 },
    });
    map.addLayer({
      id: "radius-outline",
      type: "line",
      source: "radius-circle",
      paint: { "line-color": "#4f46e5", "line-width": 2, "line-dasharray": [3, 2] },
    });
  }
}

function circleGeoJSON(lat, lng, radiusM, steps = 64) {
  const coords = [];
  for (let i = 0; i <= steps; i++) {
    const angle = (i / steps) * 2 * Math.PI;
    const dx = (radiusM / 111320) * Math.cos(angle) / Math.cos((lat * Math.PI) / 180);
    const dy = (radiusM / 110540) * Math.sin(angle);
    coords.push([lng + dx, lat + dy]);
  }
  return {
    type: "Feature",
    geometry: { type: "Polygon", coordinates: [coords] },
  };
}

// ── Score API ──────────────────────────────────────────────────────────────

async function fetchScore(lat, lng, radiusM) {
  setLoading(true);

  try {
    const url = `${API_BASE}/indicators/vitalite-culturelle?lat=${lat}&lon=${lng}&radius_m=${radiusM}`;
    const res = await fetch(url);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    renderResult(data);
  } catch (err) {
    showError(`Erreur : ${err.message}`);
  } finally {
    setLoading(false);
  }
}

function renderResult(data) {
  errorDiv.classList.add("hidden");
  hintDiv.classList.add("hidden");
  resultDiv.classList.remove("hidden");

  scoreVal.textContent = data.score.toFixed(1);
  scoreVal.style.color = scoreColor(data.score);

  dEvt.textContent  = data.nb_evenements;
  dCult.textContent = data.nb_culturels;
  dSport.textContent = data.nb_sport;
  dAsso.textContent = data.nb_associations;

  barEvt.style.setProperty("--pct",   `${data.score_evenements}%`);
  barCult.style.setProperty("--pct",  `${data.score_culturels}%`);
  barSport.style.setProperty("--pct", `${data.score_sport}%`);
  barAsso.style.setProperty("--pct",  `${data.score_associations}%`);
}

function scoreColor(score) {
  if (score >= 70) return "#16a34a";
  if (score >= 40) return "#d97706";
  return "#dc2626";
}

function showError(msg) {
  resultDiv.classList.add("hidden");
  errorDiv.classList.remove("hidden");
  errorDiv.textContent = msg;
}

function setLoading(on) {
  loadingDiv.classList.toggle("hidden", !on);
}

// ── Couches de points ──────────────────────────────────────────────────────

const loadedLayers = new Set();
const popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false });

async function loadLayer(cat) {
  if (loadedLayers.has(cat)) {
    map.setLayoutProperty(`points-${cat}`, "visibility", "visible");
    return;
  }

  const res = await fetch(`${API_BASE}/indicators/vitalite-culturelle/points?categorie=${cat}`);
  const geojson = await res.json();

  map.addSource(`src-${cat}`, { type: "geojson", data: geojson });
  map.addLayer({
    id: `points-${cat}`,
    type: "circle",
    source: `src-${cat}`,
    paint: {
      "circle-radius": 5,
      "circle-color": CATEGORY_COLORS[cat],
      "circle-opacity": 0.8,
      "circle-stroke-width": 1,
      "circle-stroke-color": "#fff",
    },
  });

  // Popup au survol
  map.on("mouseenter", `points-${cat}`, (e) => {
    map.getCanvas().style.cursor = "pointer";
    const label = e.features[0].properties.label || "—";
    popup.setLngLat(e.lngLat).setHTML(`<strong>${label}</strong>`).addTo(map);
  });
  map.on("mouseleave", `points-${cat}`, () => {
    map.getCanvas().style.cursor = "";
    popup.remove();
  });

  loadedLayers.add(cat);
}

function hideLayer(cat) {
  if (loadedLayers.has(cat)) {
    map.setLayoutProperty(`points-${cat}`, "visibility", "none");
  }
}

// Aucune couche chargée par défaut

// Toggle boutons
document.querySelectorAll(".layer-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    const cat = btn.dataset.cat;
    const isActive = btn.classList.toggle("active");
    if (isActive) {
      loadLayer(cat);
    } else {
      hideLayer(cat);
    }
  });
});
