#!/usr/bin/env bash
# =============================================================================
# start.sh — Démarrage Urban Data Explorer
# Usage : ./start.sh [--pipeline] [--orchestration]
#   --pipeline      : recharge toutes les données (ingestion + transformation + gold)
#   --orchestration : démarre le serveur Prefect + les flows planifiés (Vélib horaire, etc.)
# =============================================================================

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

# Support Linux/macOS + Git Bash Windows
if [[ -x ".venv/bin/python" ]]; then
  PYTHON_BIN=".venv/bin/python"
  UVICORN_BIN=".venv/bin/uvicorn"
elif [[ -x ".venv/Scripts/python.exe" ]]; then
  PYTHON_BIN=".venv/Scripts/python.exe"
  UVICORN_BIN=".venv/Scripts/uvicorn.exe"
else
  echo "❌ Environnement virtuel introuvable (.venv)."
  echo "   Crée-le puis installe les dépendances:"
  echo "   python -m venv .venv"
  echo "   .venv/Scripts/pip install -r requirements.txt"
  exit 1
fi

echo "╔════════════════════════════════════════╗"
echo "║       Urban Data Explorer — Paris      ║"
echo "╚════════════════════════════════════════╝"

# ── 1. Base de données ────────────────────────────────────────────────────────
echo ""
echo "▶ Démarrage PostgreSQL / PostGIS + MongoDB..."
docker compose up -d db mongodb

echo "  Attente que la base soit prête..."
until docker compose exec -T db pg_isready -U postgres -d paris_indicators -q; do
  sleep 1
done
echo "  ✓ Base prête"

# ── 2. Pipeline (optionnel) ───────────────────────────────────────────────────
if [[ "${1:-}" == "--pipeline" ]]; then
  echo ""
  echo "▶ Pipeline — Vitalité culturelle"
  "$PYTHON_BIN" -m pipeline.ingestion.vitalite_culturelle
  "$PYTHON_BIN" -m pipeline.transformation.vitalite_culturelle
  "$PYTHON_BIN" -m pipeline.indicators.vitalite_culturelle

  echo ""
  echo "▶ Pipeline — Immobilier"
  "$PYTHON_BIN" -m pipeline.ingestion.immobilier
  "$PYTHON_BIN" -m pipeline.transformation.immobilier
  "$PYTHON_BIN" -m pipeline.indicators.immobilier

  echo ""
  echo "▶ Pipeline — Vélib"
  "$PYTHON_BIN" -m pipeline.ingestion.velib
  "$PYTHON_BIN" -m pipeline.transformation.velib
  "$PYTHON_BIN" -m pipeline.indicators.velib

  echo ""
  echo "▶ Pipeline — Canicule"
  "$PYTHON_BIN" -m pipeline.ingestion.canicule
  "$PYTHON_BIN" -m pipeline.transformation.canicule
  "$PYTHON_BIN" -m pipeline.indicators.canicule

  echo ""
  echo "▶ Pipeline — Accessibilité Services"
  "$PYTHON_BIN" -m pipeline.ingestion.accessibilite_services
  "$PYTHON_BIN" -m pipeline.transformation.accessibilite_services
  "$PYTHON_BIN" -m pipeline.indicators.accessibilite_services
fi

# ── 3. Orchestration Prefect (optionnel) ─────────────────────────────────────
if [[ "${1:-}" == "--orchestration" ]] || [[ "${2:-}" == "--orchestration" ]]; then
  echo ""
  echo "▶ Démarrage serveur Prefect (port 4200)..."
  # Créer la base prefect si elle n'existe pas (Prefect a besoin de sa propre base PostgreSQL)
  docker compose exec -T db psql -U postgres -c "CREATE DATABASE prefect;" 2>/dev/null || true

  # Utiliser PostgreSQL comme backend Prefect (évite les conflits SQLite multi-processus)
  export PREFECT_API_URL="http://127.0.0.1:4200/api"
  export PREFECT_SERVER_DATABASE_CONNECTION_URL="postgresql+asyncpg://postgres:postgres@localhost:5433/prefect"

  PREFECT_API_URL="$PREFECT_API_URL" \
  PREFECT_SERVER_DATABASE_CONNECTION_URL="$PREFECT_SERVER_DATABASE_CONNECTION_URL" \
  "$PYTHON_BIN" -m prefect server start --host 0.0.0.0 &
  PREFECT_PID=$!

  echo "  Attente que le serveur Prefect soit prêt..."
  until curl -sf http://127.0.0.1:4200/api/health > /dev/null 2>&1; do sleep 1; done
  echo "  ✓ Serveur Prefect prêt (backend PostgreSQL)"

  echo "  ▸ Enregistrement des flows planifiés..."
  PREFECT_API_URL="$PREFECT_API_URL" "$PYTHON_BIN" -m pipeline.flows.velib_flow &       # Vélib — toutes les heures
  PREFECT_API_URL="$PREFECT_API_URL" "$PYTHON_BIN" -m pipeline.flows.culture_flow &     # Culture — 2h chaque nuit
  PREFECT_API_URL="$PREFECT_API_URL" "$PYTHON_BIN" -m pipeline.flows.canicule_flow &    # Canicule — 3h chaque nuit
  PREFECT_API_URL="$PREFECT_API_URL" "$PYTHON_BIN" -m pipeline.flows.immobilier_flow &  # Immobilier — dimanche 3h
  echo "  ✓ Flows planifiés enregistrés (UI : http://127.0.0.1:4200)"
fi

# ── 4. API ────────────────────────────────────────────────────────────────────
echo ""
echo "▶ Démarrage API FastAPI (port 8000)..."
"$UVICORN_BIN" api.main:app --host 0.0.0.0 --port 8000 &
API_PID=$!
echo "  ✓ API démarrée (PID $API_PID)"

# ── 4. Frontend ───────────────────────────────────────────────────────────────
echo ""
echo "▶ Démarrage frontend (port 8080)..."
"$PYTHON_BIN" -m http.server 8080 --directory . &
FRONT_PID=$!
echo "  ✓ Frontend démarré (PID $FRONT_PID)"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Dashboard : http://127.0.0.1:8080/frontend/public/index.html"
echo "  API docs  : http://127.0.0.1:8000/docs"
if [[ "${1:-}" == "--orchestration" ]] || [[ "${2:-}" == "--orchestration" ]]; then
echo "  Prefect   : http://127.0.0.1:4200"
fi
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  Ctrl+C pour tout arrêter"
echo ""

# Attendre et arrêter proprement
trap 'echo ""; echo "Arrêt..."; kill "$API_PID" "$FRONT_PID" ${PREFECT_PID:-} 2>/dev/null || true; docker compose stop db; exit 0' INT TERM
wait
