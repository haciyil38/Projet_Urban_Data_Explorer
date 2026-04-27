import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Depends
from sqlalchemy import text

from pipeline.db import get_engine
from api.security import limiter, require_api_key

router = APIRouter(
    prefix="/indicators/immobilier",
    tags=["Immobilier"],
    dependencies=[Depends(require_api_key)],
)

_GEOJSON_PATH = Path(__file__).parents[2] / "data" / "referentiel" / "arrondissements.geojson"


@router.get("/arrondissements", summary="Score immobilier par arrondissement (GeoJSON)")
def get_arrondissements():
    """
    Retourne un GeoJSON choroplèthe : contours des arrondissements enrichis
    avec score, prix m², évolution, ratio accessibilité.
    """
    try:
        with open(_GEOJSON_PATH) as f:
            geojson = json.load(f)
    except FileNotFoundError:
        raise HTTPException(status_code=503, detail="Fichier GeoJSON arrondissements introuvable")

    try:
        engine = get_engine()
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT code_insee, score, prix_m2_median, evolution_1an_pct,
                       nb_logements_sociaux, revenu_median, ratio_accessibilite, details
                FROM gold.immo_arrondissement
            """)).fetchall()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))

    # Indexer par string ET int pour matcher quelle que soit la forme
    scores = {}
    for row in rows:
        scores[str(row.code_insee)] = row
        scores[int(row.code_insee)] = row

    for i, feature in enumerate(geojson["features"]):
        feature["id"] = i   # requis pour setFeatureState MapLibre
        code = feature["properties"].get("c_arinsee")
        if code is not None and code in scores:
            row = scores[code]
            details = json.loads(row.details) if row.details else {}
            feature["properties"].update({
                "score":                float(row.score),
                "prix_m2_median":       float(row.prix_m2_median),
                "evolution_1an_pct":    float(row.evolution_1an_pct),
                "nb_logements_sociaux": int(row.nb_logements_sociaux),
                "revenu_median":        int(row.revenu_median),
                "ratio_accessibilite":  float(row.ratio_accessibilite),
                **details,
            })

    return geojson


@router.get("/evolution", summary="Évolution prix m² par arrondissement")
def get_evolution():
    """Série temporelle prix m² médian par arrondissement (2020–2024)."""
    try:
        engine = get_engine()
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT code_insee, annee, prix_m2_median, nb_transactions
                FROM gold.immo_evolution
                ORDER BY code_insee, annee
            """)).fetchall()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))

    # Grouper par arrondissement
    result = {}
    for row in rows:
        code = row.code_insee
        if code not in result:
            result[code] = {"code_insee": code, "series": []}
        result[code]["series"].append({
            "annee":          int(row.annee),
            "prix_m2_median": float(row.prix_m2_median),
            "nb_transactions":int(row.nb_transactions),
        })

    return list(result.values())
