from fastapi import APIRouter, HTTPException, Query
from pipeline.indicators.accessibilite_services import compute

router = APIRouter(
    prefix="/indicators/accessibilite-services",
    tags=["Accessibilité Services"],
)


@router.get("", summary="AccessScore pour un point GPS")
def get_access_score(
    lat:     float = Query(..., description="Latitude WGS84"),
    lon:     float = Query(..., description="Longitude WGS84"),
    profile: str   = Query("standard", description="Profil : standard | famille | senior | actif"),
    radius:  float = Query(1000.0, description="Rayon de recherche en mètres"),
):
    try:
        return compute(lat=lat, lon=lon, profile=profile, radius=radius)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Erreur calcul AccessScore : {e}")
