#!/usr/bin/env bash
# =============================================================================
# start.sh — Démarrage Urban Data Explorer
# Usage : ./start.sh [--pipeline]
#   --pipeline : recharge toutes les données (ingestion + transformation + gold)
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
echo "▶ Démarrage PostgreSQL / PostGIS..."
docker compose up -d db

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
fi

# ── 3. API ────────────────────────────────────────────────────────────────────
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
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  Ctrl+C pour tout arrêter"
echo ""

# Attendre et arrêter proprement
trap 'echo ""; echo "Arrêt..."; kill "$API_PID" "$FRONT_PID" 2>/dev/null || true; docker compose stop db; exit 0' INT TERM
wait
