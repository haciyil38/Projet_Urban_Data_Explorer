# =============================================================================
# TRANSFORMATION — Indice de Vitalité Culturelle Locale
# Silver : tables de points géolocalisés pour calcul PostGIS à la demande
#
# Architecture :
#   - silver.vitalite_points_evenements  : événements avec geom (Que Faire à Paris)
#   - silver.vitalite_points_culturels   : lieux culturels avec geom (Basilic)
#   - silver.vitalite_points_sport       : équipements sportifs géocodés (API Adresse)
#   - silver.vitalite_points_associations: associations géocodées (API Adresse)
#   - silver.vitalite_stats_reference    : totaux Paris pour normalisation gold
#
# Géocodage : API Adresse du gouvernement (api-adresse.data.gouv.fr)
#   Utilisé pour creneaux_sportifs et associations_paris qui n'ont pas de coords GPS.
# =============================================================================

import json

import pandas as pd
from sqlalchemy import text

from pipeline.db import get_engine, read_bronze
from pipeline.geocoding import geocode_dataframe

# Lieux nationaux à exclure (faussent le score résidentiel local)
LIEUX_EXCLUS = {
    "musée du louvre", "musée d'orsay", "centre pompidou",
    "beaubourg", "musée national d'art moderne", "palais de versailles"
}

# Noms génériques à exclure (bâtiments classés MH mais non-lieux culturels)
NOMS_GENERIQUES = {
    "immeuble", "bâtiment", "batiment", "maison", "villa",
    "hôtel particulier", "hotel particulier", "pavillon", "immeuble d'habitation",
    "ensemble immobilier", "groupe d'immeubles", "résidence", "residence",
}


def _init_silver_tables():
    """
    Crée les tables silver géospatiales avec index GIST.
    Nécessite l'extension PostGIS activée sur la base.
    """
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS silver.vitalite_points_evenements (
                id          TEXT,
                titre       TEXT,
                lat         DOUBLE PRECISION,
                lon         DOUBLE PRECISION,
                geom        GEOMETRY(Point, 4326)
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_vitalite_evt_geom
            ON silver.vitalite_points_evenements USING GIST(geom)
        """))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS silver.vitalite_points_culturels (
                id          TEXT,
                nom         TEXT,
                type_lieu   TEXT,
                lat         DOUBLE PRECISION,
                lon         DOUBLE PRECISION,
                geom        GEOMETRY(Point, 4326)
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_vitalite_cult_geom
            ON silver.vitalite_points_culturels USING GIST(geom)
        """))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS silver.vitalite_points_sport (
                id              TEXT,
                nom_equipement  TEXT,
                discipline      TEXT,
                lat             DOUBLE PRECISION,
                lon             DOUBLE PRECISION,
                geom            GEOMETRY(Point, 4326)
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_vitalite_sport_geom
            ON silver.vitalite_points_sport USING GIST(geom)
        """))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS silver.vitalite_points_associations (
                id      TEXT,
                titre   TEXT,
                lat     DOUBLE PRECISION,
                lon     DOUBLE PRECISION,
                geom    GEOMETRY(Point, 4326)
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_vitalite_asso_geom
            ON silver.vitalite_points_associations USING GIST(geom)
        """))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS silver.vitalite_stats_reference (
                categorie   TEXT PRIMARY KEY,
                total_paris BIGINT,
                computed_at TIMESTAMPTZ DEFAULT now()
            )
        """))
        conn.commit()
    print("  Tables silver géospatiales prêtes.")


def build_silver_points_evenements() -> int:
    """
    Extrait les événements Que Faire à Paris avec leurs coordonnées.
    lat_lon est un JSON stocké en TEXT : {"lat": float, "lon": float}.
    Filtre les entrées sans coordonnées valides (lat=0, lon=0).
    """
    df = read_bronze("que_faire_paris")

    def parse_latlon(val):
        try:
            d = json.loads(val)
            return float(d.get("lat", 0)), float(d.get("lon", 0))
        except Exception:
            return 0.0, 0.0

    coords = df["lat_lon"].apply(parse_latlon)
    df["lat"] = coords.apply(lambda x: x[0])
    df["lon"] = coords.apply(lambda x: x[1])

    # Exclure coords nulles ou hors bounding box Paris (~48.8–48.9 / 2.2–2.5)
    df = df[
        (df["lat"].between(48.80, 48.92)) &
        (df["lon"].between(2.20, 2.55))
    ]

    id_col = next((c for c in ["id", "event_id"] if c in df.columns), df.columns[0])
    titre_col = next((c for c in ["title", "titre"] if c in df.columns), None)

    rows = [
        {
            "id":    str(row[id_col]),
            "titre": str(row[titre_col]) if titre_col else None,
            "lat":   row["lat"],
            "lon":   row["lon"],
        }
        for _, row in df.iterrows()
    ]

    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(text("TRUNCATE silver.vitalite_points_evenements"))
        if rows:
            conn.execute(
                text("""
                    INSERT INTO silver.vitalite_points_evenements (id, titre, lat, lon, geom)
                    VALUES (:id, :titre, :lat, :lon, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326))
                """),
                rows,
            )
        conn.commit()

    print(f"    {len(rows)} événements géolocalisés chargés")
    return len(rows)


def build_silver_points_culturels() -> int:
    """
    Extrait les équipements culturels avec leurs coordonnées (latitude / longitude).
    Exclut les grands lieux touristiques nationaux.
    """
    df = read_bronze("equipements_culturels")

    if "nom" in df.columns:
        nom_lower = df["nom"].str.lower().str.strip()
        df = df[~nom_lower.isin(LIEUX_EXCLUS)]
        df = df[~nom_lower.isin(NOMS_GENERIQUES)]
        # Exclure aussi les noms qui commencent par ces termes génériques (ex: "Immeuble dit...")
        pattern = r"^(immeuble|bâtiment|batiment|maison|villa|hôtel particulier|hotel particulier|pavillon|résidence|residence)\b"
        df = df[~nom_lower.str.match(pattern, na=False)]

    df = df.dropna(subset=["latitude", "longitude"])
    df["lat"] = pd.to_numeric(df["latitude"], errors="coerce")
    df["lon"] = pd.to_numeric(df["longitude"], errors="coerce")
    df = df.dropna(subset=["lat", "lon"])
    df = df[df["lat"].between(48.80, 48.92) & df["lon"].between(2.20, 2.55)]

    id_col   = next((c for c in ["identifiant", "id"] if c in df.columns), df.columns[0])
    nom_col  = next((c for c in ["nom", "denomination_principale"] if c in df.columns), None)
    type_col = next((c for c in ["type_equipement", "categorie", "domaine"] if c in df.columns), None)

    rows = [
        {
            "id":       str(row[id_col]),
            "nom":      str(row[nom_col])  if nom_col  else None,
            "type_lieu":str(row[type_col]) if type_col else None,
            "lat":      row["lat"],
            "lon":      row["lon"],
        }
        for _, row in df.iterrows()
    ]

    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(text("TRUNCATE silver.vitalite_points_culturels"))
        if rows:
            conn.execute(
                text("""
                    INSERT INTO silver.vitalite_points_culturels (id, nom, type_lieu, lat, lon, geom)
                    VALUES (:id, :nom, :type_lieu, :lat, :lon, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326))
                """),
                rows,
            )
        conn.commit()

    print(f"    {len(rows)} lieux culturels géolocalisés chargés")
    return len(rows)


def build_silver_points_sport() -> int:
    """
    Géocode les équipements sportifs municipaux via l'API Adresse.
    Déduplique par équipement (le bronze contient un enregistrement par créneau).
    """
    df = read_bronze("creneaux_sportifs")

    # Dédupliquer : un équipement = une adresse à géocoder
    df_unique = df[["nom_de_l_equipement", "adresse_de_l_equipement", "code_postal_de_l_equipement"]].drop_duplicates(
        subset=["adresse_de_l_equipement", "code_postal_de_l_equipement"]
    ).dropna(subset=["adresse_de_l_equipement"])

    print(f"    {len(df_unique)} équipements uniques à géocoder...")
    geocoded = geocode_dataframe(
        df_unique,
        col_adresse="adresse_de_l_equipement",
        col_codepostal="code_postal_de_l_equipement",
        id_col="nom_de_l_equipement",
    )

    if geocoded.empty:
        print("    [SKIP] Aucun équipement géocodé")
        return 0

    # Filtrer bounding box Paris
    geocoded = geocoded[
        geocoded["lat"].between(48.80, 48.92) &
        geocoded["lon"].between(2.20, 2.55)
    ]

    rows = [
        {
            "id":             str(i),
            "nom_equipement": row["nom_de_l_equipement"] if "nom_de_l_equipement" in geocoded.columns else None,
            "discipline":     None,
            "lat":            row["lat"],
            "lon":            row["lon"],
        }
        for i, row in geocoded.iterrows()
    ]

    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(text("TRUNCATE silver.vitalite_points_sport"))
        if rows:
            conn.execute(
                text("""
                    INSERT INTO silver.vitalite_points_sport (id, nom_equipement, discipline, lat, lon, geom)
                    VALUES (:id, :nom_equipement, :discipline, :lat, :lon,
                            ST_SetSRID(ST_MakePoint(:lon, :lat), 4326))
                """),
                rows,
            )
        conn.commit()

    print(f"    {len(rows)} équipements sportifs géolocalisés chargés")
    return len(rows)


def build_silver_points_associations() -> int:
    """
    Géocode les associations parisiennes via l'API Adresse.
    Utilise adr2 (voie) + adrs_codepostal comme adresse.
    """
    try:
        df = read_bronze("associations_paris")
    except Exception:
        print("    [SKIP] Table bronze.associations_paris non disponible")
        return 0

    # Composer l'adresse depuis adr1/adr2/adr3 (prendre la première non nulle)
    def best_adr(row):
        for col in ["adr1", "adr2", "adr3"]:
            v = row.get(col)
            if v and str(v).strip() not in ("", "None"):
                return str(v).strip()
        return None

    df["adresse_composee"] = df.apply(best_adr, axis=1)
    df = df.dropna(subset=["adresse_composee"])

    print(f"    {len(df)} associations avec adresse à géocoder...")
    geocoded = geocode_dataframe(
        df,
        col_adresse="adresse_composee",
        col_codepostal="adrs_codepostal",
        id_col="id",
    )

    if geocoded.empty:
        print("    [SKIP] Aucune association géocodée")
        return 0

    # Jointure pour récupérer le titre depuis le DataFrame d'origine
    geocoded = geocoded.merge(df[["id", "titre"]], on="id", how="left")

    geocoded = geocoded[
        geocoded["lat"].between(48.80, 48.92) &
        geocoded["lon"].between(2.20, 2.55)
    ]

    rows = [
        {
            "id":    str(row["id"]),
            "titre": row["titre"] if pd.notna(row.get("titre")) else None,
            "lat":   row["lat"],
            "lon":   row["lon"],
        }
        for _, row in geocoded.iterrows()
    ]

    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(text("TRUNCATE silver.vitalite_points_associations"))
        if rows:
            conn.execute(
                text("""
                    INSERT INTO silver.vitalite_points_associations (id, titre, lat, lon, geom)
                    VALUES (:id, :titre, :lat, :lon, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326))
                """),
                rows,
            )
        conn.commit()

    print(f"    {len(rows)} associations géolocalisées chargées")
    return len(rows)


def build_stats_reference(nb_evenements: int, nb_culturels: int, nb_sport: int, nb_associations: int):
    """Stocke les totaux Paris par catégorie pour la normalisation dans le gold."""
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(text("""
            INSERT INTO silver.vitalite_stats_reference (categorie, total_paris)
            VALUES (:cat, :total)
            ON CONFLICT (categorie) DO UPDATE SET total_paris = EXCLUDED.total_paris, computed_at = now()
        """), [
            {"cat": "evenements",   "total": nb_evenements},
            {"cat": "culturels",    "total": nb_culturels},
            {"cat": "sport",        "total": nb_sport},
            {"cat": "associations", "total": nb_associations},
        ])
        conn.commit()
    print(f"    Stats référence : évènements={nb_evenements}, culturels={nb_culturels}, sport={nb_sport}, associations={nb_associations}")


def run():
    print("Silver [0/5] Initialisation tables géospatiales...")
    _init_silver_tables()

    print("Silver [1/5] Événements (Que Faire à Paris)...")
    nb_evt = build_silver_points_evenements()

    print("Silver [2/5] Équipements culturels...")
    nb_cult = build_silver_points_culturels()

    print("Silver [3/5] Équipements sportifs (géocodage API Adresse)...")
    nb_sport = build_silver_points_sport()

    print("Silver [4/5] Associations (géocodage API Adresse)...")
    nb_asso = build_silver_points_associations()

    print("Silver [5/5] Stats référence...")
    build_stats_reference(nb_evt, nb_cult, nb_sport, nb_asso)

    print("\nTransformation Silver terminée.")


if __name__ == "__main__":
    run()
