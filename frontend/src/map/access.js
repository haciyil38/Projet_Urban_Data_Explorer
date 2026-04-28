const API_BASE = "http://localhost:8000";

// ── Couleurs par catégorie access ──────────────────────────────────────────

const ACCESS_CATEGORY_COLORS = {
  commerces: "#16a34a",
  medecins:  "#0891b2",
  hopitaux:  "#dc2626",
  ecoles:    "#7c3aed",
};

// ── État access ───────────────────────────────────────────────────────────

let currentAccessRadius = 1000;

// ── UI refs access ─────────────────────────────────────────────────────────

const radiusAccessInput = document.getElementById("radius-access");
const radiusAccessLabel  = document.getElementById("radius-access-label");
const resultAccessDiv    = document.getElementById("result-access");
const hintAccessDiv      = document.getElementById("hint-access");
const loadingDiv         = document.getElementById("loading");
const errorDiv           = document.getElementById("error");

const scoreAccessVal     = document.getElementById("score-access-value");
const dComm              = document.getElementById("d-commerces");
const dMed               = document.getElementById("d-medecins");
const dHop               = document.getElementById("d-hopitaux");
const dEco               = document.getElementById("d-ecoles");
const barComm            = document.getElementById("bar-comm");
const barMed             = document.getElementById("bar-med");
const barHop             = document.getElementById("bar-hop");
const barEco             = document.getElementById("bar-eco");

// ── Rayon access ───────────────────────────────────────────────────────────

let radiusAccessDebounce = null;

radiusAccessInput.addEventListener("input", () => {
  currentAccessRadius = parseInt(radiusAccessInput.value);
  radiusAccessLabel.textContent = `${currentAccessRadius} m`;
  if (currentMarker) {
    const { lng, lat } = currentMarker.getLngLat();
    updateCircle(lat, lng, currentAccessRadius);
    clearTimeout(radiusAccessDebounce);
    radiusAccessDebounce = setTimeout(() => fetchAccessScore(lat, lng), 400);
  }
});

// ── Score API access ───────────────────────────────────────────────────────

async function fetchAccessScore(lat, lng) {
  setLoading(true);

  try {
    const url = `${API_BASE}/indicators/accessibilite-services?lat=${lat}&lon=${lng}&profile=standard`;
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

  dComm.textContent = `${data.distance_commerces_m.toFixed(0)} m`;
  dMed.textContent  = `${data.distance_medecins_m.toFixed(0)} m`;
  dHop.textContent  = `${data.distance_hopitaux_m.toFixed(0)} m`;
  dEco.textContent  = `${data.distance_ecoles_m.toFixed(0)} m`;

  barComm.style.setProperty("--pct", `${data.score_commerces}%`);
  barMed.style.setProperty("--pct",  `${data.score_medecins}%`);
  barHop.style.setProperty("--pct",  `${data.score_hopitaux}%`);
  barEco.style.setProperty("--pct",  `${data.score_ecoles}%`);
}

function scoreColor(score) {
  if (score >= 70) return "#16a34a";
  if (score >= 40) return "#d97706";
  return "#dc2626";
}

function showError(msg) {
  resultAccessDiv.classList.add("hidden");
  errorDiv.classList.remove("hidden");
  errorDiv.textContent = msg;
}

function setLoading(on) {
  loadingDiv.classList.toggle("hidden", !on);
}

// ── Couches de points access ───────────────────────────────────────────────

const loadedAccessLayers = new Set();
const accessPopup = new maplibregl.Popup({ closeButton: false, closeOnClick: false });

async function loadAccessLayer(cat) {
  if (loadedAccessLayers.has(cat)) {
    map.setLayoutProperty(`points-access-${cat}`, "visibility", "visible");
    return;
  }

  const res = await fetch(`${API_BASE}/accessibilite_services/points?categorie=${cat}`);
  const geojson = await res.json();

  map.addSource(`src-access-${cat}`, { type: "geojson", data: geojson });
  map.addLayer({
    id: `points-access-${cat}`,
    type: "circle",
    source: `src-access-${cat}`,
    paint: {
      "circle-radius": 5,
      "circle-color": ACCESS_CATEGORY_COLORS[cat],
      "circle-opacity": 0.8,
      "circle-stroke-width": 1,
      "circle-stroke-color": "#fff",
    },
  });

  // Popup au survol
  map.on("mouseenter", `points-access-${cat}`, (e) => {
    map.getCanvas().style.cursor = "pointer";
    const label = e.features[0].properties.label || "—";
    accessPopup.setLngLat(e.lngLat).setHTML(`<strong>${label}</strong>`).addTo(map);
  });
  map.on("mouseleave", `points-access-${cat}`, () => {
    map.getCanvas().style.cursor = "";
    accessPopup.remove();
  });

  loadedAccessLayers.add(cat);
}

function hideAccessLayer(cat) {
  if (loadedAccessLayers.has(cat)) {
    map.setLayoutProperty(`points-access-${cat}`, "visibility", "none");
  }
}

// Toggle boutons access
document.querySelectorAll("#tab-access .layer-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    const cat = btn.dataset.cat;
    const isActive = btn.classList.toggle("active");
    if (isActive) {
      loadAccessLayer(cat);
    } else {
      hideAccessLayer(cat);
    }
  });
});