# =============================================================================
# TRANSFORMATION — Indice de Confort Caniculaire
# Silver :
#   - canicule_refuges          : points individuels fontaines + îlots (PostGIS)
#   - canicule_par_arrondissement : données agrégées arbres/LST + centroïdes
# =============================================================================

import json
import re
from pathlib import Path

import pandas as pd
from sqlalchemy import text

from pipeline.db import init_schemas, read_bronze, load_to_silver, get_engine

_GEOJSON_PATH = Path(__file__).parents[2] / "data" / "referentiel" / "arrondissements.geojson"

# Surfaces (m²) et populations par arrondissement — sources IGN / INSEE 2020
_SURFACES_M2 = {
    "75001": 183_000,  "75002":  99_000,  "75003": 117_000, "75004": 160_000,
    "75005": 254_000,  "75006": 215_000,  "75007": 409_000, "75008": 388_000,
    "75009": 218_000,  "75010": 289_000,  "75011": 367_000, "75012": 1_639_000,
    "75013": 715_000,  "75014": 561_000,  "75015": 846_000, "75016": 1_644_000,
    "75017": 567_000,  "75018": 601_000,  "75019": 679_000, "75020": 598_000,
}
_POPULATIONS = {
    "75001":  17_000, "75002":  22_000, "75003":  35_000, "75004":  29_000,
    "75005":  60_000, "75006":  43_000, "75007":  57_000, "75008":  39_000,
    "75009":  62_000, "75010":  94_000, "75011": 155_000, "75012": 143_000,
    "75013": 184_000, "75014": 140_000, "75015": 241_000, "75016": 166_000,
    "75017": 170_000, "75018": 196_000, "75019": 187_000, "75020": 197_000,
}


def _extract_arr_code(val) -> str | None:
    if pd.isna(val):
        return None
    s = str(val).upper().strip()
    m = re.search(r'75(0(?:0[1-9]|1\d|20))', s)
    if m:
        return f"75{m.group(1)}"
    m = re.search(r'(\d{1,2})\s*(?:E[MR]?E?|ER|ÈME|IEME|IÈME)?\s*(?:ARRDT|ARR|ARROND)', s)
    if m:
        n = int(m.group(1))
        if 1 <= n <= 20:
            return f"750{n:02d}"
    m = re.search(r'\b(\d{1,2})\b', s)
    if m:
        n = int(m.group(1))
        if 1 <= n <= 20:
            return f"750{n:02d}"
    return None


def _geo_point(raw) -> tuple[float, float] | None:
    """Extrait (lat, lon) depuis un champ geo_point_2d JSON."""
    if raw is None:
        return None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return None
    lat = raw.get("lat")
    lon = raw.get("lon")
    if lat is None or lon is None:
        return None
    return float(lat), float(lon)


def _build_refuges_df() -> pd.DataFrame:
    """Combine îlots équipements, espaces verts et fontaines en un DataFrame de points."""
    rows = []

    try:
        df = read_bronze("canicule_ilots_equipements")
        for _, r in df.iterrows():
            pt = _geo_point(r.get("geo_point_2d"))
            if pt:
                rows.append({"categorie": "ilot_equip", "label": r.get("nom", ""), "lat": pt[0], "lon": pt[1]})
    except Exception as e:
        print(f"  [WARN] ilots_equipements : {e}")

    try:
        df = read_bronze("canicule_ilots_espaces_verts")
        for _, r in df.iterrows():
            pt = _geo_point(r.get("geo_point_2d"))
            if pt:
                rows.append({"categorie": "espace_vert", "label": r.get("nom", ""), "lat": pt[0], "lon": pt[1]})
    except Exception as e:
        print(f"  [WARN] ilots_espaces_verts : {e}")

    try:
        df = read_bronze("canicule_fontaines")
        for _, r in df.iterrows():
            pt = _geo_point(r.get("geo_point_2d"))
            if pt:
                label = " ".join(filter(None, [r.get("type_objet"), r.get("voie")])) or "Fontaine"
                rows.append({"categorie": "fontaine", "label": label, "lat": pt[0], "lon": pt[1]})
    except Exception as e:
        print(f"  [WARN] fontaines : {e}")

    return pd.DataFrame(rows)


def _load_refuges_to_silver(df: pd.DataFrame):
    """Crée silver.canicule_refuges avec colonne PostGIS geometry."""
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS silver"))
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        conn.execute(text("""
            DROP TABLE IF EXISTS silver.canicule_refuges;
            CREATE TABLE silver.canicule_refuges (
                id          SERIAL PRIMARY KEY,
                categorie   TEXT,
                label       TEXT,
                lat         FLOAT,
                lon         FLOAT,
                geom        GEOMETRY(Point, 4326)
            )
        """))
        conn.commit()

    rows = df.to_dict("records")
    if not rows:
        print("  [WARN] canicule_refuges vide")
        return

    with engine.connect() as conn:
        conn.execute(text("""
            INSERT INTO silver.canicule_refuges (categorie, label, lat, lon, geom)
            VALUES (:categorie, :label, :lat, :lon,
                    ST_SetSRID(ST_MakePoint(:lon, :lat), 4326))
        """), rows)
        conn.execute(text("""
            CREATE INDEX ON silver.canicule_refuges
            USING GIST (geom)
        """))
        conn.commit()

    print(f"  → silver.canicule_refuges : {len(rows)} points chargés avec index GIST")


def _build_arrondissements_df() -> pd.DataFrame:
    """Construit le tableau arrondissements avec centroïdes, arbres, LST."""
    # Centroïdes depuis GeoJSON
    with open(_GEOJSON_PATH) as f:
        geo = json.load(f)

    centroids = {}
    for feature in geo["features"]:
        props = feature["properties"]
        c = props.get("c_arinsee")      # ex 75110
        xy = props.get("geom_x_y", {})
        if c and xy:
            n = c - 75100               # 10ème → 10
            arr = f"750{n:02d}"         # "75010"
            centroids[arr] = (xy["lat"], xy["lon"])

    # Arbres agrégés
    try:
        df_arbres = read_bronze("canicule_arbres_agg")
        df_arbres["arr_code"] = df_arbres["arrondissement"].apply(_extract_arr_code)
        arbres_idx = df_arbres.dropna(subset=["arr_code"]).set_index("arr_code")
    except Exception:
        arbres_idx = pd.DataFrame()

    # LST Copernicus
    try:
        df_lst = read_bronze("canicule_lst")
        lst_idx = df_lst.set_index("arrondissement")["lst_ete_moy_c"].to_dict()
    except Exception:
        lst_idx = {}

    rows = []
    for arr, (clat, clon) in centroids.items():
        nb_arbres, circ_moy_cm = 0.0, 50.0
        if not arbres_idx.empty and arr in arbres_idx.index:
            nb_arbres   = float(arbres_idx.loc[arr].get("nb_arbres",   0) or 0)
            circ_moy_cm = float(arbres_idx.loc[arr].get("circ_moy_cm", 50) or 50)

        rows.append({
            "arrondissement": arr,
            "centroid_lat":   clat,
            "centroid_lon":   clon,
            "population":     _POPULATIONS.get(arr, 50_000),
            "surface_m2":     _SURFACES_M2.get(arr, 500_000),
            "nb_arbres":      nb_arbres,
            "circ_moy_cm":    circ_moy_cm,
            "lst_ete_moy_c":  lst_idx.get(arr),
        })

    return pd.DataFrame(rows)


def run():
    init_schemas()

    print("  Construction silver.canicule_refuges...")
    df_refuges = _build_refuges_df()
    nb = {"ilot_equip": (df_refuges["categorie"] == "ilot_equip").sum(),
          "espace_vert": (df_refuges["categorie"] == "espace_vert").sum(),
          "fontaine":    (df_refuges["categorie"] == "fontaine").sum()}
    print(f"    ilots_equip={nb['ilot_equip']} espaces_verts={nb['espace_vert']} fontaines={nb['fontaine']}")
    _load_refuges_to_silver(df_refuges)

    print("  Construction silver.canicule_par_arrondissement...")
    df_arr = _build_arrondissements_df()
    load_to_silver(df_arr, "canicule_par_arrondissement")
    print(f"  → silver.canicule_par_arrondissement : {len(df_arr)} arrondissements")


if __name__ == "__main__":
    run()
