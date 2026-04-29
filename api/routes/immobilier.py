import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Depends

from pipeline.db import get_mongo_client
from api.security import limiter, require_api_key

router = APIRouter(
    prefix="/indicators/immobilier",
    tags=["Immobilier"],
    dependencies=[Depends(require_api_key)],
)

_GEOJSON_PATH = Path(__file__).parents[2] / "data" / "referentiel" / "arrondissements.geojson"


def _get_gold_collection(name: str):
    return get_mongo_client()["paris_gold"][name]


@router.get("/arrondissements", summary="Score immobilier par arrondissement (GeoJSON)")
def get_arrondissements():
    """
    Retourne un GeoJSON choroplèthe : contours des arrondissements enrichis
    avec score, prix m², évolution, ratio accessibilité (Gold depuis MongoDB).
    """
    try:
        with open(_GEOJSON_PATH) as f:
            geojson = json.load(f)
    except FileNotFoundError:
        raise HTTPException(status_code=503, detail="Fichier GeoJSON arrondissements introuvable")

    try:
        docs = list(_get_gold_collection("immo_arrondissement").find({}, {"_id": 0}))
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))

    # Indexer par string ET int pour matcher quelle que soit la forme
    scores = {}
    for doc in docs:
        scores[str(doc["code_insee"])] = doc
        scores[int(doc["code_insee"])] = doc

    for i, feature in enumerate(geojson["features"]):
        feature["id"] = i
        code = feature["properties"].get("c_arinsee")
        if code is not None and code in scores:
            doc = scores[code]
            details = json.loads(doc["details"]) if isinstance(doc.get("details"), str) else doc.get("details", {})
            feature["properties"].update({
                "score":                float(doc.get("score", 0)),
                "prix_m2_median":       float(doc.get("prix_m2_median", 0)),
                "evolution_1an_pct":    float(doc.get("evolution_1an_pct", 0)),
                "nb_logements_sociaux": int(doc.get("nb_logements_sociaux", 0)),
                "revenu_median":        int(doc.get("revenu_median", 0)),
                "ratio_accessibilite":  float(doc.get("ratio_accessibilite", 0)),
                **(details if isinstance(details, dict) else {}),
            })

    return geojson


@router.get("/evolution", summary="Évolution prix m² par arrondissement")
def get_evolution():
    """Série temporelle prix m² médian par arrondissement (Gold depuis MongoDB)."""
    try:
        docs = list(_get_gold_collection("immo_evolution").find({}, {"_id": 0}))
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))

    result = {}
    for doc in docs:
        code = doc["code_insee"]
        if code not in result:
            result[code] = {"code_insee": code, "series": []}
        result[code]["series"].append({
            "annee":           int(doc["annee"]),
            "prix_m2_median":  float(doc["prix_m2_median"]),
            "nb_transactions": int(doc["nb_transactions"]),
        })

    for entry in result.values():
        entry["series"].sort(key=lambda x: x["annee"])

    return list(result.values())
