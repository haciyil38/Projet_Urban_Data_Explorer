"""
TRANSFORMATION — AccessScore (V2 - Ultra-Stable)
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

def _find_coord_cols(df):
    """Cherche intelligemment les colonnes de latitude et longitude."""
    lat_names = ['latitude', 'lat', 'y', 'lat_wgs84', 'y_wgs84']
    lon_names = ['longitude', 'lon', 'lng', 'x', 'lon_wgs84', 'x_wgs84']
    
    lat_col, lon_col = None, None
    cols_lower = [c.lower() for c in df.columns]
    
    for name in lat_names:
        if name in cols_lower:
            lat_col = df.columns[cols_lower.index(name)]
            break
            
    for name in lon_names:
        if name in cols_lower:
            lon_col = df.columns[cols_lower.index(name)]
            break
            
    return lat_col, lon_col

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

    # Détection automatique des colonnes
    lat_col, lon_col = _find_coord_cols(df)
    
    if not lat_col or not lon_col:
        print(f"  [SKIP] {category} : Colonnes de coordonnées non trouvées dans {df.columns.tolist()}")
        return 0

    # Conversion et nettoyage
    df['lat_clean'] = pd.to_numeric(df[lat_col], errors='coerce')
    df['lon_clean'] = pd.to_numeric(df[lon_col], errors='coerce')
    df = df.dropna(subset=['lat_clean', 'lon_clean'])

    # Filtrage BBOX Paris élargie (IDF)
    df = df[df["lat_clean"].between(48.0, 49.0) & df["lon_clean"].between(2.0, 3.0)].copy()
    
    if df.empty:
        print(f"  [SKIP] {category} : Aucun point dans la BBOX (Zone: {lat_col}/{lon_col})")
        return 0

    # Préparation des lignes pour l'insertion
    # On cherche une colonne de nom de manière flexible
    nom_cols = [c for c in df.columns if 'nom' in c.lower() or 'enseigne' in c.lower() or 'rs' in c.lower() or 'etablissement' in c.lower()]
    nom_col = nom_cols[0] if nom_cols else df.columns[0]

    rows = []
    for _, row in df.iterrows():
        rows.append({
            "id": str(row.iloc[0]), # On prend la 1ere col comme ID par défaut
            "nom": str(row[nom_col])[:200] if nom_col in df.columns else "Inconnu",
            "lat": float(row["lat_clean"]),
            "lon": float(row["lon_clean"]),
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
