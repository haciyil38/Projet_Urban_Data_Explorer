// ── AccessScore — score d'accessibilité aux services du quotidien ──────────

// ── Refs UI ───────────────────────────────────────────────────────────────

const accessRadiusInput  = document.getElementById("radius-access");
const accessRadiusLabel  = document.getElementById("radius-access-label");
const accessResultDiv    = document.getElementById("result-access");
const accessHintDiv      = document.getElementById("hint-access");
const profileSelect      = document.getElementById("profile-select");

// ── Rayon ─────────────────────────────────────────────────────────────────

let accessRadiusDebounce = null;

accessRadiusInput.addEventListener("input", () => {
  currentRadius = parseInt(accessRadiusInput.value);
  accessRadiusLabel.textContent = `${currentRadius} m`;
  if (currentMarker && activeTab === "access") {
    const { lng, lat } = currentMarker.getLngLat();
    updateCircle(lat, lng, currentRadius);
    clearTimeout(accessRadiusDebounce);
    accessRadiusDebounce = setTimeout(() => fetchAccess(lat, lng, currentRadius), 400);
  }
});

profileSelect.addEventListener("change", () => {
  if (currentMarker && activeTab === "access") {
    const { lng, lat } = currentMarker.getLngLat();
    fetchAccess(lat, lng, currentRadius);
  }
});

// ── Fetch score ───────────────────────────────────────────────────────────

async function fetchAccess(lat, lng, radiusM) {
  const profile = profileSelect.value;
  setLoading(true);
  try {
    const url = `${API_BASE}/indicators/accessibilite-services?lat=${lat}&lon=${lng}&profile=${profile}&radius=${radiusM}`;
    const res  = await fetch(url, { headers: API_HEADERS });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    renderAccess(data);
  } catch (err) {
    showError(`Accès — Erreur : ${err.message}`);
  } finally {
    setLoading(false);
  }
}

// ── Rendu résultat ────────────────────────────────────────────────────────

function renderAccess(data) {
  errorDiv.classList.add("hidden");
  accessHintDiv.classList.add("hidden");
  accessResultDiv.classList.remove("hidden");

  const scoreEl = document.getElementById("access-score-value");
  scoreEl.textContent = data.score.toFixed(1);
  scoreEl.style.color = scoreColor(data.score);

  document.getElementById("access-d-commerces").textContent = `${data.distance_commerces_m.toFixed(0)} m`;
  document.getElementById("access-d-medecins").textContent  = `${data.distance_medecins_m.toFixed(0)} m`;
  document.getElementById("access-d-hopitaux").textContent  = `${data.distance_hopitaux_m.toFixed(0)} m`;
  document.getElementById("access-d-ecoles").textContent    = `${data.distance_ecoles_m.toFixed(0)} m`;

  document.getElementById("bar-access-commerces").style.setProperty("--pct", `${data.score_commerces}%`);
  document.getElementById("bar-access-medecins").style.setProperty("--pct",  `${data.score_medecins}%`);
  document.getElementById("bar-access-hopitaux").style.setProperty("--pct",  `${data.score_hopitaux}%`);
  document.getElementById("bar-access-ecoles").style.setProperty("--pct",    `${data.score_ecoles}%`);
}

// ── Hook gestion onglets ──────────────────────────────────────────────────

document.querySelectorAll(".tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    if (btn.dataset.tab !== "access") {
      // Rien à masquer (pas de couches de points pour access pour l'instant)
    }
  });
});
