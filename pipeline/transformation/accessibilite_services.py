"""
TRANSFORMATION — AccessScore
Silver : tables de points géospatiaux avec index GIST PostGIS.
"""

from sqlalchemy import text
from pipeline.db import get_engine, read_bronze
import pandas as pd

TABLES = {
    "commerces": "silver.access_points_commerces",
    "medecins":  "silver.access_points_medecins",
    "hopitaux":  "silver.access_points_hopitaux",
    "ecoles":    "silver.access_points_ecoles",
}


def _init_silver_tables():
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS silver"))
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        for category, table in TABLES.items():
            conn.execute(text(f"""
                CREATE TABLE IF NOT EXISTS {table} (
                    id     TEXT,
                    nom    TEXT,
                    lat    DOUBLE PRECISION,
                    lon    DOUBLE PRECISION,
                    source TEXT,
                    geom   GEOMETRY(Point, 4326)
                )
            """))
            conn.execute(text(f"""
                CREATE INDEX IF NOT EXISTS idx_access_{category}_geom
                ON {table} USING GIST(geom)
            """))
        conn.commit()
    print("  Tables silver accessibilité prêtes.")


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

    lat_col = "latitude" if "latitude" in df.columns else "lat"
    lon_col = "longitude" if "longitude" in df.columns else "lon"

    df["lat_clean"] = pd.to_numeric(df[lat_col], errors="coerce")
    df["lon_clean"] = pd.to_numeric(df[lon_col], errors="coerce")
    df = df.dropna(subset=["lat_clean", "lon_clean"])

    rows = [
        {
            "id":     str(row.get("id", i)),
            "nom":    str(row.get("nom", ""))[:200],
            "lat":    float(row["lat_clean"]),
            "lon":    float(row["lon_clean"]),
            "source": category,
        }
        for i, (_, row) in enumerate(df.iterrows())
    ]

    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(text(f"TRUNCATE {table}"))
        if rows:
            conn.execute(
                text(f"""
                    INSERT INTO {table} (id, nom, lat, lon, source, geom)
                    VALUES (:id, :nom, :lat, :lon, :source,
                            ST_SetSRID(ST_MakePoint(:lon, :lat), 4326))
                """),
                rows,
            )
        conn.commit()

    print(f"  → {len(rows)} points silver pour {category}")
    return len(rows)


def run():
    _init_silver_tables()
    for cat in TABLES:
        _load_category(cat)
    print("Transformation Silver accessibilité terminée.")


if __name__ == "__main__":
    run()
