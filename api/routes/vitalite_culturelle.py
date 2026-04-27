from fastapi import APIRouter, Query, HTTPException, Request, Depends
from pydantic import BaseModel

from pipeline.indicators.vitalite_culturelle import compute, setup
from pipeline.db import get_engine
from sqlalchemy import text
from api.security import limiter, require_api_key

router = APIRouter(
    prefix="/indicators/vitalite-culturelle",
    tags=["Vitalité Culturelle"],
    dependencies=[Depends(require_api_key)],
)


class ScoreDetail(BaseModel):
    lat: float
    lon: float
    radius_m: float
    score: float
    nb_evenements: int
    nb_culturels: int
    nb_sport: int
    nb_associations: int
    score_evenements: float
    score_culturels: float
    score_sport: float
    score_associations: float


class SourcesMeta(BaseModel):
    nb_evenements: int
    nb_culturels: int
    nb_sport: int
    nb_associations: int
    updated_at: str


@router.get("", response_model=ScoreDetail, summary="Score de vitalité culturelle pour un point")
@limiter.limit("60/minute")
def get_score(
    request: Request,
    lat: float = Query(..., ge=48.80, le=48.92, description="Latitude WGS84"),
    lon: float = Query(..., ge=2.20,  le=2.55,  description="Longitude WGS84"),
    radius_m: float = Query(500, ge=100, le=5000, description="Rayon en mètres"),
):
    """
    Calcule l'indice de vitalité culturelle pour un point (lat, lon) dans un rayon donné.

    - **score** : 0–100 (50 = densité moyenne parisienne, 100 = double)
    - **radius_m** : rayon de recherche en mètres (100–5000, défaut 500)
    """
    try:
        result = compute(lat=lat, lon=lon, radius_m=radius_m)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Erreur calcul score : {e}")
    return result


@router.get("/points", summary="Points géolocalisés par catégorie (GeoJSON)")
def get_points(
    categorie: str = Query(..., description="evenements | culturels | sport | associations"),
):
    """
    Retourne les points silver en GeoJSON pour affichage carte.
    """
    table_map = {
        "evenements":   ("silver.vitalite_points_evenements",  "titre"),
        "culturels":    ("silver.vitalite_points_culturels",   "nom"),
        "sport":        ("silver.vitalite_points_sport",       "nom_equipement"),
        "associations": ("silver.vitalite_points_associations", "titre"),
    }
    if categorie not in table_map:
        raise HTTPException(status_code=400, detail=f"Catégorie inconnue : {categorie}")

    table, label_col = table_map[categorie]
    try:
        engine = get_engine()
        with engine.connect() as conn:
            rows = conn.execute(
                text(f"SELECT id, {label_col} as label, lat, lon FROM {table} WHERE lat IS NOT NULL")
            ).fetchall()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))

    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [row.lon, row.lat]},
            "properties": {"id": row.id, "label": row.label, "categorie": categorie},
        }
        for row in rows
    ]
    return {"type": "FeatureCollection", "features": features}


@router.get("/sources", response_model=SourcesMeta, summary="Metadata des sources silver")
def get_sources():
    """Retourne le nombre de points géolocalisés par catégorie et la date de dernière mise à jour."""
    try:
        engine = get_engine()
        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT categorie, total_paris, computed_at FROM silver.vitalite_stats_reference")
            ).fetchall()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Erreur lecture silver : {e}")

    stats = {row.categorie: row for row in rows}
    updated_at = max(row.computed_at for row in rows).isoformat() if rows else "N/A"

    return {
        "nb_evenements":  stats["evenements"].total_paris  if "evenements"  in stats else 0,
        "nb_culturels":   stats["culturels"].total_paris   if "culturels"   in stats else 0,
        "nb_sport":       stats["sport"].total_paris       if "sport"       in stats else 0,
        "nb_associations":stats["associations"].total_paris if "associations" in stats else 0,
        "updated_at":     updated_at,
    }
