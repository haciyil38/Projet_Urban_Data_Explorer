from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from pipeline.indicators.accessibilite_services import compute

router = APIRouter(
    prefix="/indicators/accessibilite-services",
    tags=["Accessibilite Services"],
)

class AccessScoreDetail(BaseModel):
    lat: float
    lon: float
    profile: str
    radius: float
    score: float
    distance_commerces_m: float
    distance_medecins_m: float
    distance_hopitaux_m: float
    distance_ecoles_m: float
    score_commerces: float
    score_medecins: float
    score_hopitaux: float
    score_ecoles: float

@router.get("", response_model=AccessScoreDetail, summary="AccessScore pour un point")
def get_access_score(
    lat: float = Query(..., description="Latitude WGS84"),
    lon: float = Query(..., description="Longitude WGS84"),
    profile: str = Query(
        "standard",
        description="Profil de ponderation: standard | famille | senior | actif",
    ),
    radius: float = Query(1000.0, description="Rayon de recherche en metres"),
):
    try:
        return compute(lat=lat, lon=lon, profile=profile, radius=radius)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Erreur calcul AccessScore : {e}")
