# =============================================================================
# CONFIG — Paramètres globaux du projet Urban Data Explorer
# =============================================================================

import os
from dotenv import load_dotenv

load_dotenv()

# --- Base de données PostgreSQL ---
DB_HOST     = os.getenv("DB_HOST", "localhost")
DB_PORT     = int(os.getenv("DB_PORT", 5433))
DB_NAME     = os.getenv("DB_NAME", "paris_indicators")
DB_USER     = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "postgres")
DB_URL      = f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# --- Base de données MongoDB (Data Lake Bronze) ---
MONGO_HOST  = os.getenv("MONGO_HOST", "localhost")
MONGO_PORT  = int(os.getenv("MONGO_PORT", 27017))
MONGO_URL   = f"mongodb://{MONGO_HOST}:{MONGO_PORT}/"

# --- Arrondissements Paris (codes INSEE) ---
ARRONDISSEMENTS = [f"750{str(i).zfill(2)}" for i in range(1, 21)]

# --- Sécurité API ---
API_KEY         = os.getenv("API_KEY", "urban-data-explorer-2024")
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://127.0.0.1:8080,http://localhost:8080").split(",")

# --- Limite API OpenDataSoft (max offset) ---
MAX_OFFSET = 9900

# =============================================================================
# INDICATEUR 1 — Indice de Vitalité Culturelle Locale
# =============================================================================
WEIGHTS_VITALITE = {
    "evenements":       0.35,
    "occupation_sport": 0.25,
    "lieux_culturels":  0.20,
    "associations":     0.20,
}

# =============================================================================
# INDICATEUR 2 — AccessScore
# =============================================================================

# Paramètres de décroissance exponentielle λ (tolérance distance usagers)
LAMBDA_ACCESS = {
    "commerces": 1 / 230,   # ~230 m
    "medecins":  1 / 700,   # ~700 m
    "hopitaux":  1 / 2300,  # ~2.3 km
    "ecoles":    1 / 350,   # ~350 m
}

WEIGHTS_ACCESS = {
    "commerces": 0.25,
    "medecins":  0.30,
    "hopitaux":  0.25,
    "ecoles":    0.20,
}

# =============================================================================
# INDICATEUR 3 — Indice de Confort Caniculaire
# Sources : îlots fraîcheur équipements + espaces verts frais + fontaines + arbres
# =============================================================================
WEIGHTS_CANICULAIRE = {
    "refuges_frais":      0.35,   # îlots équipements + espaces verts frais + fontaines
    "couverture_arboree": 0.35,   # arbres géolocalisés (densité × circonférence)
    "lst":                0.30,   # température de surface estivale ERA5-Land (Copernicus)
}

# =============================================================================
# INDICATEUR 4 — Disponibilité Vélib
# =============================================================================
VELIB_SEUILS = {
    "vide":       0.0,   # taux == 0
    "pleine":     0.9,   # taux >= 90%
    # entre les deux → "équilibrée"
}
