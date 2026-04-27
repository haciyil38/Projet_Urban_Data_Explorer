"""
TRANSFORMATION — AccessScore
Silver : tables de points geospatiaux par categorie de services.
"""

from sqlalchemy import text

from pipeline.db import get_engine, read_bronze


TABLES = {
    "commerces": "silver.access_points_commerces",
    "medecins": "silver.access_points_medecins",
    "hopitaux": "silver.access_points_hopitaux",
    "ecoles": "silver.access_points_ecoles",
}


def _init_silver_tables():
    engine = get_engine()
    with engine.connect() as conn:
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

    # Nettoyage minimal + bbox Paris
    for col in ("lat", "lon"):
        df[col] = df[col].astype(float)
    df = df[
        df["lat"].between(48.80, 48.92) &
        df["lon"].between(2.20, 2.55)
    ].copy()
    id_col = "id" if "id" in df.columns else df.columns[0]
    df = df.drop_duplicates(subset=[id_col, "lat", "lon"])

    rows = [
        {
            "id": str(row[id_col]),
            "nom": row["nom"] if "nom" in df.columns else None,
            "lat": float(row["lat"]),
            "lon": float(row["lon"]),
            "source": row["source"] if "source" in df.columns else None,
        }
        for _, row in df.iterrows()
    ]

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

    print("Silver [1/4] Commerces...")
    _load_category("commerces")

    print("Silver [2/4] Medecins...")
    _load_category("medecins")

    print("Silver [3/4] Hopitaux...")
    _load_category("hopitaux")

    print("Silver [4/4] Ecoles...")
    _load_category("ecoles")

    print("\nTransformation Silver accessibilite terminee.")


if __name__ == "__main__":
    run()
