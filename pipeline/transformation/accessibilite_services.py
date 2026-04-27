"""
TRANSFORMATION — AccessScore
Silver : tables de points geospatiaux par categorie de services.
"""

from sqlalchemy import text
from pipeline.db import get_engine, read_bronze
import pandas as pd

TABLES = {
    "commerces": "silver.access_points_commerces",
    "medecins": "silver.access_points_medecins",
    "hopitaux": "silver.access_points_hopitaux",
    "ecoles": "silver.access_points_ecoles",
}

def _init_silver_tables():
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS silver"))
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        for category, table in TABLES.items():
            conn.execute(
                text(f"""
                    CREATE TABLE IF NOT EXISTS {table} (
                        id        TEXT,
                        nom       TEXT,
                        lat       DOUBLE PRECISION,
                        lon       DOUBLE PRECISION,
                        source    TEXT,
                        geom      GEOMETRY(Point, 4326)
                    )
                """)
            )
            conn.execute(
                text(f"""
                    CREATE INDEX IF NOT EXISTS idx_access_{category}_geom
                    ON {table} USING GIST(geom)
                """)
            )
        conn.commit()
    print("  Tables silver accessibilite pretes.")

def _load_category(category: str) -> int:
    table = TABLES[category]
    bronze_table = f"access_{category}_raw"
    try:
        df = read_bronze(bronze_table)
    except Exception:
        print(f"  [SKIP] bronze.{bronze_table} introuvable")
        return 0

    if df.empty:
        print(f"  [SKIP] bronze.{bronze_table} vide")
        return 0

    # Mapping flexible des colonnes
    mapping = {
        "commerces": {"id": "siret", "nom": "enseigne1Etablissement", "lat": "latitude", "lon": "longitude"},
        "medecins": {"id": "Identifiant PP", "nom": "Nom d'exercice", "lat": "latitude", "lon": "longitude"},
        "hopitaux": {"id": "nofinesset", "nom": "rs", "lat": "lat", "lon": "lng"},
        "ecoles": {"id": "identifiant_de_l_etablissement", "nom": "nom_etablissement", "lat": "latitude", "lon": "longitude"}
    }
    
    m = mapping.get(category, {})
    
    # Nettoyage et conversion
    lat_col = m.get("lat") if m.get("lat") in df.columns else "lat"
    lon_col = m.get("lon") if m.get("lon") in df.columns else "lon"
    id_col = m.get("id") if m.get("id") in df.columns else df.columns[0]
    nom_col = m.get("nom") if m.get("nom") in df.columns else None

    # Conversion forcée
    df["lat"] = pd.to_numeric(df[lat_col] if lat_col in df.columns else None, errors='coerce')
    df["lon"] = pd.to_numeric(df[lon_col] if lon_col in df.columns else None, errors='coerce')
    
    # Filtrage BBOX Paris
    df = df[df["lat"].between(48.80, 48.92) & df["lon"].between(2.20, 2.55)].copy()
    
    if df.empty:
        print(f"  [SKIP] {category} : Aucun point dans la BBOX Paris")
        return 0

    rows = []
    for _, row in df.iterrows():
        rows.append({
            "id": str(row[id_col]),
            "nom": str(row[nom_col]) if nom_col and nom_col in df.columns else "Inconnu",
            "lat": float(row["lat"]),
            "lon": float(row["lon"]),
            "source": category
        })

    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(text(f"TRUNCATE {table}"))
        if rows:
            conn.execute(
                text(f"""
                    INSERT INTO {table} (id, nom, lat, lon, source, geom)
                    VALUES (:id, :nom, :lat, :lon, :source, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326))
                """),
                rows,
            )
        conn.commit()

    print(f"    {len(rows)} points silver pour {category}")
    return len(rows)

def run():
    print("Silver [0/5] Initialisation tables...")
    _init_silver_tables()
    for cat in TABLES.keys():
        print(f"Silver - Traitement {cat}...")
        _load_category(cat)
    print("\nTransformation Silver accessibilite terminee.")

if __name__ == "__main__":
    run()
