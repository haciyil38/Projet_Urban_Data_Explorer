from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel

from pipeline.indicators.velib import compute, setup
from pipeline.db import get_engine
from sqlalchemy import text

router = APIRouter(prefix="/indicators/velib", tags=["Vélib"])


class VelibScore(BaseModel):
    lat: float
    lon: float
    radius_m: float
    score: float
    nb_stations: int
    total_velos_dispo: int
    total_velos_meca: int
    total_velos_elec: int
    total_bornes_dispo: int
    taux_moyen: float
    score_densite: float
    score_disponibilite: float


@router.get("", response_model=VelibScore, summary="Score Vélib pour un point")
def get_score(
    lat: float = Query(..., ge=48.70, le=49.00, description="Latitude WGS84"),
    lon: float = Query(..., ge=2.10,  le=2.65,  description="Longitude WGS84"),
    radius_m: float = Query(500, ge=100, le=5000, description="Rayon en mètres"),
):
    """
    Calcule le score d'accès Vélib pour un point (lat, lon) dans un rayon donné.

    - **score** : 0–100 (50 = densité moyenne métropole)
    - **score_densite** : densité de stations vs moyenne métropole
    - **score_disponibilite** : taux moyen de vélos disponibles × 100
    """
    try:
        result = compute(lat=lat, lon=lon, radius_m=radius_m)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Erreur calcul score Vélib : {e}")
    return result


@router.get("/stations", summary="Stations Vélib en GeoJSON")
def get_stations():
    """
    Retourne toutes les stations Vélib installées en GeoJSON pour affichage carte.
    Chaque feature porte : nom, capacité, vélos dispo (meca + élec), bornes libres, taux (%).
    """
    engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT station_id, nom, capacite,
                   num_velos_dispo, num_velos_meca, num_velos_elec,
                   num_bornes_dispo, taux_disponibilite,
                   lat, lon
            FROM silver.velib_stations
            WHERE is_installed = TRUE
            ORDER BY station_id
        """)).mappings().fetchall()

    features = [
        {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [float(r["lon"]), float(r["lat"])],
            },
            "properties": {
                "label":       r["nom"] or r["station_id"],
                "station_id":  r["station_id"],
                "capacite":    int(r["capacite"] or 0),
                "velos_dispo": int(r["num_velos_dispo"] or 0),
                "velos_meca":  int(r["num_velos_meca"]  or 0),
                "velos_elec":  int(r["num_velos_elec"]  or 0),
                "bornes_dispo":int(r["num_bornes_dispo"] or 0),
                "taux":        round(float(r["taux_disponibilite"] or 0) * 100, 1),
            },
        }
        for r in rows
    ]

    return {"type": "FeatureCollection", "features": features}
