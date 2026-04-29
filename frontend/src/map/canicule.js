// ── Canicule — score de confort caniculaire par rayon GPS ─────────────────

// ── Refs UI ───────────────────────────────────────────────────────────────

const caniculeRadiusInput = document.getElementById("radius-canicule");
const caniculeRadiusLabel = document.getElementById("radius-canicule-label");
const caniculeResultDiv   = document.getElementById("result-canicule");
const caniculeHintDiv     = document.getElementById("hint-canicule");

// ── Rayon ─────────────────────────────────────────────────────────────────

let caniculeRadiusDebounce = null;

caniculeRadiusInput.addEventListener("input", () => {
  currentRadius = parseInt(caniculeRadiusInput.value);
  caniculeRadiusLabel.textContent = `${currentRadius} m`;
  if (currentMarker && activeTab === "canicule") {
    const { lng, lat } = currentMarker.getLngLat();
    updateCircle(lat, lng, currentRadius);
    clearTimeout(caniculeRadiusDebounce);
    caniculeRadiusDebounce = setTimeout(() => fetchCanicule(lat, lng, currentRadius), 400);
  }
});

// ── Fetch score ───────────────────────────────────────────────────────────

async function fetchCanicule(lat, lng, radiusM) {
  setLoading(true);
  try {
    const url = `${API_BASE}/indicators/canicule?lat=${lat}&lon=${lng}&radius_m=${radiusM}`;
    const res = await fetch(url, { headers: API_HEADERS });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    renderCanicule(data);
  } catch (err) {
    showError(`Canicule — Erreur : ${err.message}`);
  } finally {
    setLoading(false);
  }
}

// ── Rendu résultat ────────────────────────────────────────────────────────

function renderCanicule(data) {
  errorDiv.classList.add("hidden");
  caniculeHintDiv.classList.add("hidden");
  caniculeResultDiv.classList.remove("hidden");

  const scoreEl = document.getElementById("canicule-score");
  scoreEl.textContent = data.score.toFixed(1);
  scoreEl.style.color = scoreColor(data.score);

  document.getElementById("canicule-refuges").textContent =
    data.nb_refuges.toLocaleString("fr-FR") + " équipements";
  document.getElementById("canicule-fontaines").textContent =
    data.nb_fontaines.toLocaleString("fr-FR");
  document.getElementById("canicule-equip").textContent =
    data.nb_ilots_equip.toLocaleString("fr-FR");
  document.getElementById("canicule-verts").textContent =
    data.nb_espaces_verts.toLocaleString("fr-FR");
  document.getElementById("canicule-arbres").textContent =
    data.nb_arbres.toLocaleString("fr-FR") + " arbres";
  document.getElementById("canicule-lst").textContent =
    data.lst_ete_moy_c != null ? data.lst_ete_moy_c.toFixed(1) + " °C (ERA5-Land)" : "—";

  document.getElementById("bar-canicule-refuges").style.setProperty("--pct", `${data.score_refuges}%`);
  document.getElementById("bar-canicule-arboree").style.setProperty("--pct", `${data.score_arboree}%`);
  document.getElementById("bar-canicule-lst").style.setProperty("--pct",     `${data.score_lst}%`);
}

// ── Couches de points ─────────────────────────────────────────────────────

const CANICULE_POINT_COLORS = {
  "ilots-equipements": "#f97316",   // orange
  "espaces-verts":     "#16a34a",   // vert
  "fontaines":         "#3b82f6",   // bleu
};

const caniculeLoadedLayers = new Set();
const caniculePopup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 8 });

async function loadCaniculeLayer(cat) {
  const id = `canicule-pts-${cat}`;
  if (caniculeLoadedLayers.has(cat)) {
    map.setLayoutProperty(id, "visibility", "visible");
    return;
  }

  try {
    const res = await fetch(`${API_BASE}/indicators/canicule/points/${cat}`, { headers: API_HEADERS });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const geojson = await res.json();

    map.addSource(`canicule-src-${cat}`, { type: "geojson", data: geojson });
    map.addLayer({
      id,
      type: "circle",
      source: `canicule-src-${cat}`,
      paint: {
        "circle-radius": 5,
        "circle-color":  CANICULE_POINT_COLORS[cat],
        "circle-opacity": 1,
        "circle-stroke-width": 1,
        "circle-stroke-color": "#fff",
      },
    });

    map.on("mouseenter", id, (e) => {
      map.getCanvas().style.cursor = "pointer";
      const p = e.features[0].properties;
      let html = `<strong>${p.label || "—"}</strong>`;
      if (p.type)             html += `<br>${p.type}`;
      if (p.statut_ouverture) html += `<br>${p.statut_ouverture}`;
      if (p.dispo !== undefined) html += `<br>Dispo : ${p.dispo === "OUI" ? "✅" : "🔧 indisponible"}`;
      caniculePopup.setLngLat(e.lngLat).setHTML(html).addTo(map);
    });
    map.on("mouseleave", id, () => {
      map.getCanvas().style.cursor = "";
      caniculePopup.remove();
    });

    caniculeLoadedLayers.add(cat);
  } catch (err) {
    console.error(`Canicule layer ${cat}:`, err);
  }
}

function hideCaniculeLayer(cat) {
  if (caniculeLoadedLayers.has(cat)) {
    map.setLayoutProperty(`canicule-pts-${cat}`, "visibility", "none");
  }
}

function hideAllCaniculeLayers() {
  caniculeLoadedLayers.forEach((cat) => hideCaniculeLayer(cat));
}

document.querySelectorAll("[data-canicule-cat]").forEach((btn) => {
  btn.addEventListener("click", () => {
    const cat = btn.getAttribute("data-canicule-cat");
    const isActive = btn.classList.toggle("active");
    if (isActive) loadCaniculeLayer(cat);
    else          hideCaniculeLayer(cat);
  });
});

// ── Hook gestion onglets ──────────────────────────────────────────────────

document.querySelectorAll(".tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    const tab = btn.dataset.tab;
    if (tab !== "canicule") {
      hideAllCaniculeLayers();
    }
  });
});
