// ── Config ─────────────────────────────────────────────────────────────────
const API_BASE = "https://8000-i05hf4z5kat7286s0apxj-0653cabd.us1.manus.computer";

const CATEGORY_COLORS = {
  culturels: "#7c3aed",
  evenements: "#0891b2",
  sport: "#16a34a",
  associations: "#d97706",
};

// ── État ───────────────────────────────────────────────────────────────────
let currentMarker = null;
let currentRadius = 500;
let currentProfile = "standard";
let activeTab = "immo";

// ── DOM ────────────────────────────────────────────────────────────────────
const mapDiv = document.getElementById("map");
const radiusInput = document.getElementById("radius");
const radiusLabel = document.getElementById("radius-label");
const profileSelect = document.getElementById("profile-select");
const resultDiv = document.getElementById("result-culture");
const scoreVal = document.getElementById("score-value");
const dEvt = document.getElementById("d-evenements");
const dCult = document.getElementById("d-culturels");
const dSport = document.getElementById("d-sport");
const dAsso = document.getElementById("d-associations");
const barEvt = document.getElementById("bar-evt");
const barCult = document.getElementById("bar-cult");
const barSport = document.getElementById("bar-sport");
const barAsso = document.getElementById("bar-asso");
const hintDiv = document.getElementById("hint-culture");

const resultAccessDiv = document.getElementById("result-access");
const scoreAccessVal = document.getElementById("score-access-value");
const dAccCom = document.getElementById("d-access-commerces");
const dAccMed = document.getElementById("d-access-medecins");
const dAccHop = document.getElementById("d-access-hopitaux");
const dAccEco = document.getElementById("d-access-ecoles");
const barAccCom = document.getElementById("bar-access-com");
const barAccMed = document.getElementById("bar-access-med");
const barAccHop = document.getElementById("bar-access-hop");
const barAccEco = document.getElementById("bar-access-eco");
const hintAccessDiv = document.getElementById("hint-access");

const errorDiv = document.getElementById("error");
const loadingDiv = document.getElementById("loading");

// ── Carte ──────────────────────────────────────────────────────────────────
const map = new maplibregl.Map({
  container: "map",
  style: "https://openmaptiles.geo.data.gouv.fr/styles/osm-bright/style.json",
  center: [2.3522, 48.8566],
  zoom: 12,
});

// ── Événements ─────────────────────────────────────────────────────────────
radiusInput.addEventListener("input", (e) => {
  currentRadius = parseInt(e.target.value);
  radiusLabel.textContent = `${currentRadius} m`;
  if (currentMarker) {
    const { lng, lat } = currentMarker.getLngLat();
    updateCircle(lat, lng, currentRadius);
    debouncedFetch(lat, lng);
  }
});

profileSelect.addEventListener("change", (e) => {
  currentProfile = e.target.value;
  if (currentMarker) {
    const { lng, lat } = currentMarker.getLngLat();
    fetchAccessScore(lat, lng, currentProfile);
  }
});

let debounceTimer = null;
function debouncedFetch(lat, lng) {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => {
    if (activeTab === "culture") fetchCultureScore(lat, lng, currentRadius);
    if (activeTab === "access") fetchAccessScore(lat, lng, currentProfile);
  }, 400);
}

map.on("click", (e) => {
  const { lng, lat } = e.lngLat;
  placeMarker(lat, lng);
  
  if (activeTab === "culture") {
    updateCircle(lat, lng, currentRadius);
    fetchCultureScore(lat, lng, currentRadius);
  } else if (activeTab === "access") {
    fetchAccessScore(lat, lng, currentProfile);
  }
});

// ── Marker & Cercle ────────────────────────────────────────────────────────
function placeMarker(lat, lng) {
  if (currentMarker) currentMarker.remove();
  currentMarker = new maplibregl.Marker({ color: "#4f46e5" })
    .setLngLat([lng, lat])
    .addTo(map);
}

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
  return { type: "Feature", geometry: { type: "Polygon", coordinates: [coords] } };
}

// ── API Vitalité Culturelle ────────────────────────────────────────────────
async function fetchCultureScore(lat, lng, radiusM) {
  setLoading(true);
  try {
    const url = `${API_BASE}/indicators/vitalite-culturelle?lat=${lat}&lon=${lng}&radius_m=${radiusM}`;
    const res = await fetch(url);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    renderCultureResult(data);
  } catch (err) {
    showError(`Erreur : ${err.message}`);
  } finally {
    setLoading(false);
  }
}

function renderCultureResult(data) {
  errorDiv.classList.add("hidden");
  hintDiv.classList.add("hidden");
  resultDiv.classList.remove("hidden");
  scoreVal.textContent = data.score.toFixed(1);
  scoreVal.style.color = scoreColor(data.score);
  dEvt.textContent = data.nb_evenements;
  dCult.textContent = data.nb_culturels;
  dSport.textContent = data.nb_sport;
  dAsso.textContent = data.nb_associations;
  barEvt.style.setProperty("--pct", `${data.score_evenements}%`);
  barCult.style.setProperty("--pct", `${data.score_culturels}%`);
  barSport.style.setProperty("--pct", `${data.score_sport}%`);
  barAsso.style.setProperty("--pct", `${data.score_associations}%`);
}

// ── API AccessScore ────────────────────────────────────────────────────────
async function fetchAccessScore(lat, lng, profile) {
  setLoading(true);
  try {
    const url = `${API_BASE}/indicators/accessibilite-services?lat=${lat}&lon=${lng}&profile=${profile}`;
    const res = await fetch(url);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    renderAccessResult(data);
  } catch (err) {
    showError(`Erreur : ${err.message}`);
  } finally {
    setLoading(false);
  }
}

function renderAccessResult(data) {
  errorDiv.classList.add("hidden");
  hintAccessDiv.classList.add("hidden");
  resultAccessDiv.classList.remove("hidden");
  
  scoreAccessVal.textContent = data.score.toFixed(1);
  scoreAccessVal.style.color = scoreColor(data.score);
  
  dAccCom.textContent = `${Math.round(data.distance_commerces_m)} m`;
  dAccMed.textContent = `${Math.round(data.distance_medecins_m)} m`;
  dAccHop.textContent = `${Math.round(data.distance_hopitaux_m)} m`;
  dAccEco.textContent = `${Math.round(data.distance_ecoles_m)} m`;
  
  barAccCom.style.setProperty("--pct", `${data.score_commerces * 100}%`);
  barAccMed.style.setProperty("--pct", `${data.score_medecins * 100}%`);
  barAccHop.style.setProperty("--pct", `${data.score_hopitaux * 100}%`);
  barAccEco.style.setProperty("--pct", `${data.score_ecoles * 100}%`);
}

// ── Helpers UI ─────────────────────────────────────────────────────────────
function scoreColor(score) {
  if (score >= 70) return "#16a34a";
  if (score >= 40) return "#d97706";
  return "#dc2626";
}

function showError(msg) {
  resultDiv.classList.add("hidden");
  resultAccessDiv.classList.add("hidden");
  errorDiv.classList.remove("hidden");
  errorDiv.textContent = msg;
}

function setLoading(on) {
  loadingDiv.classList.toggle("hidden", !on);
}

// ── Gestion Onglets (Surcharge immo.js) ───────────────────────────────────
map.on('load', () => {
  document.querySelectorAll(".tab").forEach(btn => {
    btn.addEventListener("click", () => {
      activeTab = btn.dataset.tab;
      
      // Nettoyage cercle si on quitte culture
      if (activeTab !== "culture" && map.getLayer("radius-fill")) {
        map.setLayoutProperty("radius-fill", "visibility", "none");
        map.setLayoutProperty("radius-outline", "visibility", "none");
      } else if (activeTab === "culture" && map.getLayer("radius-fill")) {
        map.setLayoutProperty("radius-fill", "visibility", "visible");
        map.setLayoutProperty("radius-outline", "visibility", "visible");
      }
      
      // Si on a un marker, on relance le calcul pour le nouvel onglet
      if (currentMarker) {
        const { lng, lat } = currentMarker.getLngLat();
        if (activeTab === "culture") fetchCultureScore(lat, lng, currentRadius);
        if (activeTab === "access") fetchAccessScore(lat, lng, currentProfile);
      }
    });
  });
});

// ── Couches de points (Vitalité) ──────────────────────────────────────────
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

document.querySelectorAll(".layer-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    const cat = btn.dataset.cat;
    const isActive = btn.classList.toggle("active");
    if (isActive) loadLayer(cat); else hideLayer(cat);
  });
});
