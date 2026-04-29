// ── Vélib — score d'accès et couche stations ──────────────────────────────

// ── Refs UI ───────────────────────────────────────────────────────────────

const velibRadiusInput = document.getElementById("radius-velib");
const velibRadiusLabel = document.getElementById("radius-velib-label");
const velibResultDiv   = document.getElementById("result-velib");
const velibHintDiv     = document.getElementById("hint-velib");

const velibScoreVal    = document.getElementById("velib-score-value");
const vNbStations      = document.getElementById("v-nb-stations");
const vVelosDispo      = document.getElementById("v-velos-dispo");
const vVelosElec       = document.getElementById("v-velos-elec");
const vBornesDispo     = document.getElementById("v-bornes-dispo");
const vTaux            = document.getElementById("v-taux");
const barVelibDens     = document.getElementById("bar-velib-dens");
const barVelibDispo    = document.getElementById("bar-velib-dispo");

// ── Rayon Vélib ───────────────────────────────────────────────────────────

let velibRadiusDebounce = null;

velibRadiusInput.addEventListener("input", () => {
  currentRadius = parseInt(velibRadiusInput.value);
  velibRadiusLabel.textContent = `${currentRadius} m`;
  if (currentMarker) {
    const { lng, lat } = currentMarker.getLngLat();
    updateCircle(lat, lng, currentRadius);
    clearTimeout(velibRadiusDebounce);
    velibRadiusDebounce = setTimeout(() => fetchVelib(lat, lng, currentRadius), 400);
  }
});

// ── Fetch score Vélib ─────────────────────────────────────────────────────

async function fetchVelib(lat, lng, radiusM) {
  setLoading(true);
  try {
    const url = `${API_BASE}/indicators/velib?lat=${lat}&lon=${lng}&radius_m=${radiusM}`;
    const res = await fetch(url);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    renderVelib(data);
  } catch (err) {
    showError(`Vélib — Erreur : ${err.message}`);
  } finally {
    setLoading(false);
  }
}

// ── Rendu résultat ────────────────────────────────────────────────────────

function renderVelib(data) {
  errorDiv.classList.add("hidden");
  velibHintDiv.classList.add("hidden");
  velibResultDiv.classList.remove("hidden");

  velibScoreVal.textContent = data.score.toFixed(1);
  velibScoreVal.style.color = scoreColor(data.score);

  vNbStations.textContent  = data.nb_stations;
  vVelosDispo.textContent  = data.total_velos_dispo;
  vVelosElec.textContent   = data.total_velos_elec;
  vBornesDispo.textContent = data.total_bornes_dispo;
  vTaux.textContent        = `${(data.taux_moyen * 100).toFixed(1)} %`;

  barVelibDens.style.setProperty("--pct",  `${data.score_densite}%`);
  barVelibDispo.style.setProperty("--pct", `${data.score_disponibilite}%`);
}

// ── Couche stations Vélib ─────────────────────────────────────────────────

let velibLayerLoaded = false;

async function loadVelibLayer() {
  if (velibLayerLoaded) {
    map.setLayoutProperty("velib-stations", "visibility", "visible");
    return;
  }

  const res  = await fetch(`${API_BASE}/indicators/velib/stations`);
  const geojson = await res.json();

  map.addSource("velib-src", { type: "geojson", data: geojson });

  // Cercle coloré selon le taux de disponibilité
  map.addLayer({
    id: "velib-stations",
    type: "circle",
    source: "velib-src",
    paint: {
      "circle-radius": 5,
      "circle-color": [
        "step",
        ["get", "taux"],
        "#dc2626",   // rouge  : < 20 %
        20, "#d97706", // orange : 20–40 %
        40, "#16a34a", // vert   : ≥ 40 %
      ],
      "circle-opacity": 0.85,
      "circle-stroke-width": 1,
      "circle-stroke-color": "#fff",
    },
  });

  // Popup au survol
  const velibPopup = new maplibregl.Popup({
    closeButton: false,
    closeOnClick: false,
    offset: 8,
  });

  map.on("mouseenter", "velib-stations", (e) => {
    map.getCanvas().style.cursor = "pointer";
    const p = e.features[0].properties;
    velibPopup
      .setLngLat(e.lngLat)
      .setHTML(
        `<strong>${p.label}</strong><br>` +
        `🚲 ${p.velos_dispo} vélo${p.velos_dispo !== 1 ? "s" : ""} ` +
        `(🔋 ${p.velos_elec} élec.)<br>` +
        `🅿️ ${p.bornes_dispo} borne${p.bornes_dispo !== 1 ? "s" : ""} libre${p.bornes_dispo !== 1 ? "s" : ""}<br>` +
        `📊 ${p.taux} %`
      )
      .addTo(map);
  });

  map.on("mouseleave", "velib-stations", () => {
    map.getCanvas().style.cursor = "";
    velibPopup.remove();
  });

  velibLayerLoaded = true;
}

function hideVelibLayer() {
  if (velibLayerLoaded) {
    map.setLayoutProperty("velib-stations", "visibility", "none");
  }
}

// ── Bouton toggle couche ──────────────────────────────────────────────────

document.getElementById("btn-velib-layer").addEventListener("click", function () {
  const isActive = this.classList.toggle("active");
  if (isActive) {
    loadVelibLayer();
  } else {
    hideVelibLayer();
  }
});

// ── Légende disponibilité ─────────────────────────────────────────────────
// (insérée dynamiquement dans le tab Vélib, après le bouton de couche)

(function injectVelibLegend() {
  const row = document.createElement("div");
  row.className = "velib-legend";
  row.innerHTML =
    `<span class="velib-dot" style="background:#dc2626"></span>&lt; 20 %&ensp;` +
    `<span class="velib-dot" style="background:#d97706"></span>20–40 %&ensp;` +
    `<span class="velib-dot" style="background:#16a34a"></span>≥ 40 %`;
  const layersRow = document.querySelector("#tab-velib .layers-row");
  layersRow.after(row);
})();
