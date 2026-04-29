import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import text

from pipeline.db import get_engine
from api.security import limiter, require_api_key

router = APIRouter(
    prefix="/indicators/canicule",
    tags=["Canicule"],
    dependencies=[Depends(require_api_key)],
)


class CaniculeScore(BaseModel):
    lat: float
    lon: float
    radius_m: float
    score: float
    nb_refuges: int
    nb_fontaines: int
    nb_ilots_equip: int
    nb_espaces_verts: int
    nb_arbres: int
    circ_moy_cm: float
    lst_ete_moy_c: float | None
    score_refuges: float
    score_arboree: float
    score_lst: float


@router.get("", response_model=CaniculeScore, summary="Score de confort caniculaire pour un point")
@limiter.limit("30/minute")
def get_score(
    request: Request,
    lat:      float = Query(..., ge=48.70, le=49.00, description="Latitude WGS84"),
    lon:      float = Query(..., ge=2.10,  le=2.65,  description="Longitude WGS84"),
    radius_m: float = Query(500, ge=100, le=3000,    description="Rayon en mètres"),
):
    """
    Calcule l'indice de confort caniculaire pour un point (lat, lon) dans un rayon donné.

    - **score** : 0–100 (refuges frais 35% + couverture arborée 35% + LST ERA5-Land 30%)
    - **score_refuges** : densité d'îlots fraîcheur et fontaines vs moyenne Paris
    - **score_arboree** : couverture arborée de l'arrondissement
    - **score_lst** : fraîcheur de surface estivale Copernicus (inversée)
    """
    try:
        engine = get_engine()
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT * FROM gold.score_canicule(:lat, :lon, :r)"),
                {"lat": lat, "lon": lon, "r": radius_m},
            ).mappings().fetchone()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Erreur calcul score canicule : {e}")
    if row is None:
        raise HTTPException(status_code=503, detail="Aucun résultat — relancez ./start.sh --pipeline")
    return dict(row)


def _bronze_to_geojson(table: str, label_col: str, extra_props: list[str]) -> dict:
    engine = get_engine()
    cols = ", ".join(["geo_point_2d", label_col] + extra_props)
    with engine.connect() as conn:
        rows = conn.execute(text(f"SELECT {cols} FROM bronze.{table}")).mappings().fetchall()

    features = []
    for r in rows:
        geo = r["geo_point_2d"]
        if geo is None:
            continue
        if isinstance(geo, str):
            geo = json.loads(geo)
        lon_val, lat_val = geo.get("lon"), geo.get("lat")
        if lon_val is None or lat_val is None:
            continue
        props = {"label": r[label_col] or "—"}
        for col in extra_props:
            props[col] = r[col]
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon_val, lat_val]},
            "properties": props,
        })
    return {"type": "FeatureCollection", "features": features}


@router.get("/points/ilots-equipements", summary="Îlots fraîcheur équipements (GeoJSON)")
@limiter.limit("20/minute")
def get_ilots_equipements(request: Request):
    try:
        return _bronze_to_geojson("canicule_ilots_equipements", "nom", ["type", "statut_ouverture"])
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/points/espaces-verts", summary="Îlots fraîcheur espaces verts frais (GeoJSON)")
@limiter.limit("20/minute")
def get_espaces_verts(request: Request):
    try:
        return _bronze_to_geojson("canicule_ilots_espaces_verts", "nom", ["type", "statut_ouverture"])
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/points/fontaines", summary="Fontaines à boire (GeoJSON)")
@limiter.limit("20/minute")
def get_fontaines(request: Request):
    try:
        return _bronze_to_geojson("canicule_fontaines", "voie", ["type_objet", "dispo"])
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))
