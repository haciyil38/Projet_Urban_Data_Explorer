# =============================================================================
# INGESTION — Indice de Confort Caniculaire
# Bronze : données brutes depuis Paris OpenData + LST Copernicus ERA5-Land
# =============================================================================

import glob
import json
from pathlib import Path

import requests
import pandas as pd
from pipeline.config import MAX_OFFSET
from pipeline.db import init_schemas, load_to_bronze

BASE_PARIS = "https://opendata.paris.fr/api/explore/v2.1/catalog/datasets"


def _fetch_all(url: str, params: dict = None, limit: int = 100) -> pd.DataFrame:
    p = {"limit": limit, "offset": 0}
    if params:
        p.update(params)
    records = []
    while True:
        for attempt in range(3):
            try:
                r = requests.get(url, params=p, timeout=90)
                r.raise_for_status()
                break
            except requests.exceptions.Timeout:
                if attempt == 2:
                    raise
                print(f"    timeout, retry {attempt + 1}/3...", end="\r")
        batch = r.json().get("results", [])
        records.extend(batch)
        print(f"    {len(records)} enregistrements...", end="\r")
        if len(batch) < limit or p["offset"] >= MAX_OFFSET:
            break
        p["offset"] += limit
    print()
    return pd.DataFrame(records)


def fetch_ilots_equipements() -> pd.DataFrame:
    print("  Appel API Îlots fraîcheur équipements...")
    return _fetch_all(f"{BASE_PARIS}/ilots-de-fraicheur-equipements-activites/records")


def fetch_ilots_espaces_verts() -> pd.DataFrame:
    print("  Appel API Îlots fraîcheur espaces verts...")
    return _fetch_all(f"{BASE_PARIS}/ilots-de-fraicheur-espaces-verts-frais/records")


def fetch_fontaines() -> pd.DataFrame:
    print("  Appel API Fontaines à boire...")
    return _fetch_all(f"{BASE_PARIS}/fontaines-a-boire/records")


def fetch_arbres_par_arrondissement() -> pd.DataFrame:
    """Agrège côté serveur pour éviter de télécharger 200 000+ enregistrements."""
    print("  Appel API Arbres (agrégation par arrondissement)...")
    params = {
        "select": "arrondissement,count(*) as nb_arbres,avg(circonferenceencm) as circ_moy_cm",
        "group_by": "arrondissement",
        "limit": 30,
    }
    r = requests.get(f"{BASE_PARIS}/les-arbres/records", params=params, timeout=90)
    r.raise_for_status()
    df = pd.DataFrame(r.json().get("results", []))
    print(f"    {len(df)} arrondissements")
    return df


def fetch_lst_par_arrondissement() -> pd.DataFrame:
    """
    Lit le fichier ERA5-Land (skin temperature, mois d'été 2022-2024) téléchargé
    depuis Copernicus CDS et calcule la LST moyenne estivale par arrondissement
    via interpolation bilinéaire au centroïde de chaque arrondissement.
    """
    import xarray as xr
    import numpy as np

    # Chercher le fichier .nc dans data/bronze/
    nc_files = glob.glob(str(Path(__file__).parents[2] / "data" / "bronze" / "*.nc"))
    if not nc_files:
        raise FileNotFoundError("Aucun fichier .nc trouvé dans data/bronze/ — téléchargez les données ERA5-Land depuis Copernicus CDS")

    nc_path = nc_files[0]
    print(f"  Lecture LST : {Path(nc_path).name}")

    ds = xr.open_dataset(nc_path)
    # Moyenne sur tous les mois d'été (juin/juil/août 2022-2024) → grille 2D
    skt_mean = ds["skt"].mean(dim="valid_time") - 273.15  # Kelvin → Celsius

    # Charger les contours arrondissements pour obtenir les centroïdes
    geojson_path = Path(__file__).parents[2] / "data" / "referentiel" / "arrondissements.geojson"
    with open(geojson_path) as f:
        geojson = json.load(f)

    rows = []
    for feature in geojson["features"]:
        props = feature["properties"]
        # Centroïde depuis le champ geom_x_y du GeoJSON Paris
        centroid = props.get("geom_x_y", {})
        lat = centroid.get("lat")
        lon = centroid.get("lon")
        if lat is None or lon is None:
            continue

        c_arinsee = props.get("c_arinsee")  # ex: 75110 pour le 10ème
        # Convertir c_arinsee (751XX) → code INSEE "750XX"
        arr_num = c_arinsee - 75100
        arr_code = f"750{arr_num:02d}"

        # Interpolation bilinéaire au centroïde
        lst_val = float(skt_mean.interp(
            latitude=lat,
            longitude=lon,
            method="linear",
        ).values)

        rows.append({
            "arrondissement": arr_code,
            "lst_ete_moy_c":  round(lst_val, 2),
        })

    df = pd.DataFrame(rows).sort_values("arrondissement").reset_index(drop=True)
    print(f"  LST extraite pour {len(df)} arrondissements — min {df['lst_ete_moy_c'].min():.1f}°C / max {df['lst_ete_moy_c'].max():.1f}°C")
    return df


def run():
    init_schemas()
    load_to_bronze(fetch_ilots_equipements(),          "canicule_ilots_equipements")
    load_to_bronze(fetch_ilots_espaces_verts(),        "canicule_ilots_espaces_verts")
    load_to_bronze(fetch_fontaines(),                  "canicule_fontaines")
    load_to_bronze(fetch_arbres_par_arrondissement(),  "canicule_arbres_agg")
    load_to_bronze(fetch_lst_par_arrondissement(),     "canicule_lst")
    print("Ingestion canicule terminée.")


if __name__ == "__main__":
    run()
