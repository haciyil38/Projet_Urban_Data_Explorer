"""
INGESTION — AccessScore
Bronze : données réelles depuis FINESS Île-de-France (officiel) + OpenStreetMap Overpass.

Sources :
  - Hôpitaux/urgences   : data.iledefrance.fr — FINESS, catégories CHR/CH/MCO
  - Médecins/centres    : data.iledefrance.fr — FINESS, centres de santé et libéraux
  - Commerces aliment.  : OpenStreetMap Overpass API (supermarché, épicerie, boulangerie…)
  - Écoles mat./élém.   : OpenStreetMap Overpass API (amenity=school/kindergarten)
"""

import requests
import pandas as pd
from pipeline.db import init_schemas, load_to_bronze

# ── FINESS Île-de-France ───────────────────────────────────────────────────

FINESS_IDF_URL = "https://data.iledefrance.fr/api/explore/v2.1/catalog/datasets/finess/records"

# Catégories FINESS pour hôpitaux et urgences
FINESS_HOPITAUX_CATS = ["1101", "1102", "1104", "1110"]

# Catégories FINESS pour médecins / centres de santé
FINESS_MEDECINS_CATS = ["2103", "2201", "2206"]

# ── OpenStreetMap Overpass ─────────────────────────────────────────────────

# Instances publiques en ordre de priorité — tentées dans l'ordre en cas d'échec
OVERPASS_MIRRORS = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.osm.ch/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]

# Bounding box Paris intra-muros (légèrement élargie)
PARIS_BBOX = "48.81,2.22,48.91,2.42"

OVERPASS_COMMERCES = (
    f"[out:json][timeout:120];"
    f"(node[shop~'supermarket|convenience|bakery|butcher|greengrocer|grocery|deli|farm']({PARIS_BBOX});"
    f"way[shop~'supermarket|convenience|bakery|butcher|greengrocer|grocery|deli|farm']({PARIS_BBOX}););"
    f"out center;"
)

OVERPASS_ECOLES = (
    f"[out:json][timeout:120];"
    f"(node[amenity~'school|kindergarten']({PARIS_BBOX});"
    f"way[amenity~'school|kindergarten']({PARIS_BBOX}););"
    f"out center;"
)


def _fetch_finess(categagretab_codes: list[str]) -> pd.DataFrame:
    """Télécharge depuis FINESS Île-de-France tous les établissements Paris des catégories données."""
    cats_filter = " OR ".join([f'categagretab="{c}"' for c in categagretab_codes])
    where = f'dep_code="75" AND ({cats_filter})'

    rows = []
    offset = 0
    limit = 100

    while True:
        params = {
            "where": where,
            "select": "nofinesset,rs,libcategagretab,coord",
            "limit": limit,
            "offset": offset,
        }
        r = requests.get(FINESS_IDF_URL, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()

        batch = data.get("results", [])
        if not batch:
            break

        for rec in batch:
            coord = rec.get("coord") or {}
            lat = coord.get("lat")
            lon = coord.get("lon")
            if lat is None or lon is None:
                continue
            rows.append({
                "id":        rec.get("nofinesset", ""),
                "nom":       rec.get("rs", ""),
                "categorie": rec.get("libcategagretab", ""),
                "latitude":  float(lat),
                "longitude": float(lon),
            })

        total = data.get("total_count") or 0
        offset += limit
        if offset >= total:
            break

    df = pd.DataFrame(rows)
    print(f"  → {len(df)} établissements récupérés (FINESS IDF)")
    return df


def _fetch_overpass(query: str, label: str) -> pd.DataFrame:
    """Télécharge des points OSM via Overpass avec fallback sur plusieurs instances."""
    last_exc = None
    for mirror in OVERPASS_MIRRORS:
        try:
            print(f"    Overpass → {mirror.split('/')[2]}...", end="\r")
            r = requests.post(
                mirror,
                data={"data": query},
                headers={"Accept": "*/*"},
                timeout=180,
            )
            r.raise_for_status()
            elements = r.json().get("elements", [])
            break
        except Exception as exc:
            print(f"    ✗ {mirror.split('/')[2]} : {exc}")
            last_exc = exc
    else:
        raise RuntimeError(f"Toutes les instances Overpass ont échoué pour {label}") from last_exc

    rows = []
    for el in elements:
        lat = el.get("lat") or el.get("center", {}).get("lat")
        lon = el.get("lon") or el.get("center", {}).get("lon")
        if lat is None or lon is None:
            continue
        tags = el.get("tags", {})
        nom = (tags.get("name") or tags.get("brand") or label)[:200]
        rows.append({
            "id":        str(el.get("id", "")),
            "nom":       nom,
            "categorie": tags.get("shop") or tags.get("amenity") or label,
            "latitude":  float(lat),
            "longitude": float(lon),
        })

    df = pd.DataFrame(rows)
    print(f"  → {len(df)} points récupérés (OSM Overpass — {label})")
    return df


def fetch_hopitaux() -> pd.DataFrame:
    print("  Hôpitaux : FINESS Île-de-France...")
    return _fetch_finess(FINESS_HOPITAUX_CATS)


def fetch_medecins() -> pd.DataFrame:
    print("  Médecins / centres de santé : FINESS Île-de-France...")
    return _fetch_finess(FINESS_MEDECINS_CATS)


def fetch_commerces() -> pd.DataFrame:
    print("  Commerces alimentaires : OpenStreetMap Overpass...")
    return _fetch_overpass(OVERPASS_COMMERCES, "commerce_alimentaire")


def fetch_ecoles() -> pd.DataFrame:
    print("  Écoles : OpenStreetMap Overpass...")
    return _fetch_overpass(OVERPASS_ECOLES, "ecole")


def run():
    init_schemas()
    load_to_bronze(fetch_hopitaux(),   "access_hopitaux_raw")
    load_to_bronze(fetch_medecins(),   "access_medecins_raw")
    load_to_bronze(fetch_commerces(),  "access_commerces_raw")
    load_to_bronze(fetch_ecoles(),     "access_ecoles_raw")
    print("Ingestion accessibilité terminée.")


if __name__ == "__main__":
    run()
