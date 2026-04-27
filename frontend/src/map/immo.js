// ── Immobilier — choroplèthe arrondissements ──────────────────────────────

let evolutionData = {};
let timelineChart = null;
let choroplethLoaded = false;
let featureById = {};       // id MapLibre → props
let featureByInsee = {};    // c_arinsee  → { id, props }
let selectedFeatureId = null;

// Charge les données gold et affiche la choroplèthe
async function loadChoropleth() {
  if (choroplethLoaded) return;

  const [geoRes, evoRes] = await Promise.all([
    fetch(`${API_BASE}/indicators/immobilier/arrondissements`, { headers: API_HEADERS }),
    fetch(`${API_BASE}/indicators/immobilier/evolution`, { headers: API_HEADERS }),
  ]);

  const geojson   = await geoRes.json();
  const evolution = await evoRes.json();

  // Index évolution par code_insee
  evolution.forEach(d => { evolutionData[d.code_insee] = d.series; });

  // Indexer les features et remplir la liste déroulante
  geojson.features.forEach((f, i) => {
    featureById[i]                       = f.properties;
    featureByInsee[f.properties.c_arinsee] = { id: i, props: f.properties };
  });

  const select = document.getElementById("arr-select");
  const sorted = [...geojson.features].sort((a, b) => a.properties.c_arinsee - b.properties.c_arinsee);
  sorted.forEach(f => {
    const opt = document.createElement("option");
    opt.value = f.properties.c_arinsee;
    opt.textContent = f.properties.l_ar;
    select.appendChild(opt);
  });

  map.addSource("arrondissements", { type: "geojson", data: geojson });

  // Insérer AVANT les routes pour que les routes restent visibles par-dessus
  const BEFORE_ROADS = "tunnel_service_case";

  // Couche remplie — couleur par prix m² (vert=abordable, rouge=cher)
  map.addLayer({
    id: "arrondissements-fill",
    type: "fill",
    source: "arrondissements",
    paint: {
      "fill-color": [
        "interpolate", ["linear"],
        ["coalesce", ["get", "prix_m2_median"], 10000],
        7500,  "#16a34a",   // vert   — abordable
        9500,  "#84cc16",
        11000, "#facc15",   // jaune  — moyen
        13000, "#f97316",
        15000, "#dc2626",   // rouge  — très cher
      ],
      "fill-opacity": 0.6,
    },
  }, BEFORE_ROADS);

  // Contour arrondissements — aussi sous les routes
  map.addLayer({
    id: "arrondissements-outline",
    type: "line",
    source: "arrondissements",
    paint: {
      "line-color": "#fff",
      "line-width": 1.5,
      "line-opacity": 0.8,
    },
  }, BEFORE_ROADS);

  // Survol — highlight par-dessus le fill mais sous les routes
  map.addLayer({
    id: "arrondissements-hover",
    type: "fill",
    source: "arrondissements",
    paint: {
      "fill-color": "#fff",
      "fill-opacity": ["case", ["boolean", ["feature-state", "hover"], false], 0.2, 0],
    },
  }, BEFORE_ROADS);

  // Sélection — contour épais au-dessus de tout (pas de beforeId)
  map.addLayer({
    id: "arrondissements-selected",
    type: "line",
    source: "arrondissements",
    paint: {
      "line-color": "#4f46e5",
      "line-width": ["case", ["boolean", ["feature-state", "selected"], false], 4, 0],
      "line-opacity": 1,
    },
  });

  let hoveredId = null;

  map.on("mousemove", "arrondissements-fill", (e) => {
    map.getCanvas().style.cursor = "pointer";
    if (hoveredId !== null) {
      map.setFeatureState({ source: "arrondissements", id: hoveredId }, { hover: false });
    }
    hoveredId = e.features[0].id;
    map.setFeatureState({ source: "arrondissements", id: hoveredId }, { hover: true });
  });

  map.on("mouseleave", "arrondissements-fill", () => {
    map.getCanvas().style.cursor = "";
    if (hoveredId !== null) {
      map.setFeatureState({ source: "arrondissements", id: hoveredId }, { hover: false });
    }
    hoveredId = null;
  });

  // Clic carte — sélectionne et synchronise la liste déroulante
  map.on("click", "arrondissements-fill", (e) => {
    const props = e.features[0].properties;
    const select = document.getElementById("arr-select");
    select.value = props.c_arinsee;
    selectArrondissement(props.c_arinsee);
  });

  choroplethLoaded = true;
}

const CHOROPLETH_LAYERS = ["arrondissements-fill", "arrondissements-outline", "arrondissements-hover", "arrondissements-selected"];

function hideChoropleth() {
  if (!choroplethLoaded) return;
  CHOROPLETH_LAYERS.forEach(id => map.setLayoutProperty(id, "visibility", "none"));
}

async function showChoropleth() {
  if (!choroplethLoaded) { await loadChoropleth(); }
  CHOROPLETH_LAYERS.forEach(id => map.setLayoutProperty(id, "visibility", "visible"));
}

// ── Affichage résultat immobilier ─────────────────────────────────────────

function showImmoResult(props) {
  document.getElementById("result-immo").classList.remove("hidden");

  document.getElementById("immo-arr").textContent    = props.l_ar ?? props.c_arinsee;
  document.getElementById("immo-prix").textContent   = `${Math.round(props.prix_m2_median).toLocaleString("fr-FR")} €/m²`;
  const evol = props.evolution_1an_pct ?? 0;
  const evolEl = document.getElementById("immo-evol");
  evolEl.textContent  = `${evol > 0 ? "+" : ""}${evol.toFixed(1)} %`;
  evolEl.style.color  = evol >= 0 ? "#16a34a" : "#dc2626";
  document.getElementById("immo-revenu").textContent  = `${Math.round(props.revenu_median).toLocaleString("fr-FR")} €/an`;
  document.getElementById("immo-ratio").textContent   = `${props.ratio_accessibilite?.toFixed(2) ?? "—"} mois/m²`;
  document.getElementById("immo-social").textContent  = (props.nb_logements_sociaux ?? 0).toLocaleString("fr-FR");

  // Timeline
  const series = evolutionData[String(props.c_arinsee)] ?? [];
  renderTimeline(series);
}

function renderTimeline(series) {
  const labels = series.map(d => d.annee);
  const values = series.map(d => Math.round(d.prix_m2_median));
  const ctx    = document.getElementById("timeline-chart").getContext("2d");

  if (timelineChart) timelineChart.destroy();

  timelineChart = new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [{
        data:            values,
        borderColor:     "#4f46e5",
        backgroundColor: "rgba(79,70,229,0.08)",
        fill:            true,
        tension:         0.3,
        pointRadius:     3,
      }],
    },
    options: {
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { font: { size: 10 } } },
        y: {
          ticks: {
            font: { size: 10 },
            callback: v => `${v.toLocaleString("fr-FR")} €`,
          },
        },
      },
    },
  });
}

// ── Liste déroulante + sélection carte ───────────────────────────────────

function selectArrondissement(insee) {
  const entry = featureByInsee[insee] || featureByInsee[parseInt(insee)];
  if (!entry) return;

  // Déselectionner le précédent
  if (selectedFeatureId !== null) {
    map.setFeatureState({ source: "arrondissements", id: selectedFeatureId }, { selected: false });
  }
  selectedFeatureId = entry.id;
  map.setFeatureState({ source: "arrondissements", id: selectedFeatureId }, { selected: true });

  showImmoResult(entry.props);
}

document.getElementById("arr-select").addEventListener("change", (e) => {
  if (!e.target.value) return;
  selectArrondissement(e.target.value);
});

// ── Gestion onglets ───────────────────────────────────────────────────────

document.querySelectorAll(".tab").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".tab-content").forEach(c => c.classList.add("hidden"));
    btn.classList.add("active");

    const tab = btn.dataset.tab;
    document.getElementById(`tab-${tab}`).classList.remove("hidden");

    if (tab === "immo") {
      showChoropleth();
    } else {
      hideChoropleth();
    }
  });
});

// Charger et afficher la choroplèthe après le premier rendu complet de la carte
map.once("idle", () => showChoropleth());
