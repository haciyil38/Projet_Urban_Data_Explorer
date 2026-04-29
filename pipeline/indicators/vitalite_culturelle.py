# =============================================================================
# INDICATEUR — Indice de Vitalité Culturelle Locale
# Gold : score calculé à la demande pour un point (lat, lon) et un rayon
#
# Architecture :
#   - gold.score_vitalite_culturelle(lat, lon, radius_m) : fonction SQL PostGIS
#   - compute(lat, lon, radius_m)                        : wrapper Python
#
# Normalisation :
#   score_i = min(100, count_radius / count_attendu * 100)
#   où count_attendu = total_paris * (π·r²) / surface_paris
#   → score 100 = densité double de la moyenne parisienne
#   → score 50  = densité égale à la moyenne parisienne
# =============================================================================

from sqlalchemy import text
import pandas as pd
from pipeline.db import get_engine, load_to_mongo_gold

# Surface Paris intra-muros en m² (105,4 km²)
PARIS_AREA_M2 = 105_400_000.0

# Poids par catégorie (doit sommer à 1.0)
WEIGHTS = {
    "evenements":   0.35,
    "culturels":    0.35,
    "sport":        0.15,
    "associations": 0.15,
}


def _create_gold_function():
    """
    Crée ou remplace la fonction SQL gold.score_vitalite_culturelle.
    Prend (lat, lon, radius_m) et retourne score + détail par catégorie.

    Normalisation par densité :
      score_i = min(100, count_rayon / count_attendu * 50)
      count_attendu = total_paris * (π·r²) / surface_paris
      → 50 = densité égale à la moyenne parisienne
      → 100 = double de la densité moyenne parisienne
    """
    sql = f"""
    CREATE OR REPLACE FUNCTION gold.score_vitalite_culturelle(
        p_lat      DOUBLE PRECISION,
        p_lon      DOUBLE PRECISION,
        p_radius_m DOUBLE PRECISION DEFAULT 500
    )
    RETURNS TABLE (
        score              DOUBLE PRECISION,
        nb_evenements      BIGINT,
        nb_culturels       BIGINT,
        nb_sport           BIGINT,
        nb_associations    BIGINT,
        score_evenements   DOUBLE PRECISION,
        score_culturels    DOUBLE PRECISION,
        score_sport        DOUBLE PRECISION,
        score_associations DOUBLE PRECISION,
        radius_m           DOUBLE PRECISION
    )
    LANGUAGE plpgsql
    AS $$
    DECLARE
        pt          GEOMETRY  := ST_SetSRID(ST_MakePoint(p_lon, p_lat), 4326);
        pt_geog     GEOGRAPHY := pt::GEOGRAPHY;
        area_m2     DOUBLE PRECISION := pi() * p_radius_m * p_radius_m;
        paris_area  DOUBLE PRECISION := {PARIS_AREA_M2};

        total_evt   BIGINT; total_cult BIGINT; total_sport BIGINT; total_asso BIGINT;
        cnt_evt     BIGINT; cnt_cult   BIGINT; cnt_sport   BIGINT; cnt_asso   BIGINT;
        s_evt       DOUBLE PRECISION;
        s_cult      DOUBLE PRECISION;
        s_sport     DOUBLE PRECISION;
        s_asso      DOUBLE PRECISION;
        s_total     DOUBLE PRECISION;
    BEGIN
        -- Totaux Paris pour normalisation
        SELECT total_paris INTO total_evt   FROM silver.vitalite_stats_reference WHERE categorie = 'evenements';
        SELECT total_paris INTO total_cult  FROM silver.vitalite_stats_reference WHERE categorie = 'culturels';
        SELECT total_paris INTO total_sport FROM silver.vitalite_stats_reference WHERE categorie = 'sport';
        SELECT total_paris INTO total_asso  FROM silver.vitalite_stats_reference WHERE categorie = 'associations';

        -- Comptages dans le rayon (ST_DWithin geography = mètres réels)
        SELECT COUNT(*) INTO cnt_evt   FROM silver.vitalite_points_evenements   WHERE ST_DWithin(geom::GEOGRAPHY, pt_geog, p_radius_m);
        SELECT COUNT(*) INTO cnt_cult  FROM silver.vitalite_points_culturels    WHERE ST_DWithin(geom::GEOGRAPHY, pt_geog, p_radius_m);
        SELECT COUNT(*) INTO cnt_sport FROM silver.vitalite_points_sport        WHERE ST_DWithin(geom::GEOGRAPHY, pt_geog, p_radius_m);
        SELECT COUNT(*) INTO cnt_asso  FROM silver.vitalite_points_associations WHERE ST_DWithin(geom::GEOGRAPHY, pt_geog, p_radius_m);

        -- Scores par densité relative (50 = moyenne Paris, 100 = double)
        s_evt   := LEAST(100.0, cnt_evt::DOUBLE PRECISION   / GREATEST(COALESCE(total_evt,  1) * area_m2 / paris_area, 0.001) * 50.0);
        s_cult  := LEAST(100.0, cnt_cult::DOUBLE PRECISION  / GREATEST(COALESCE(total_cult, 1) * area_m2 / paris_area, 0.001) * 50.0);
        s_sport := LEAST(100.0, cnt_sport::DOUBLE PRECISION / GREATEST(COALESCE(total_sport,1) * area_m2 / paris_area, 0.001) * 50.0);
        s_asso  := LEAST(100.0, cnt_asso::DOUBLE PRECISION  / GREATEST(COALESCE(total_asso, 1) * area_m2 / paris_area, 0.001) * 50.0);

        s_total := ROUND((
            s_evt   * {WEIGHTS['evenements']}   +
            s_cult  * {WEIGHTS['culturels']}    +
            s_sport * {WEIGHTS['sport']}        +
            s_asso  * {WEIGHTS['associations']}
        )::NUMERIC, 2);

        RETURN QUERY SELECT
            s_total,
            cnt_evt, cnt_cult, cnt_sport, cnt_asso,
            ROUND(s_evt::NUMERIC,   2)::DOUBLE PRECISION,
            ROUND(s_cult::NUMERIC,  2)::DOUBLE PRECISION,
            ROUND(s_sport::NUMERIC, 2)::DOUBLE PRECISION,
            ROUND(s_asso::NUMERIC,  2)::DOUBLE PRECISION,
            p_radius_m;
    END;
    $$;
    """
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(text(sql))
        conn.commit()
    print("  Fonction gold.score_vitalite_culturelle créée.")


def compute(lat: float, lon: float, radius_m: float = 500) -> dict:
    """
    Calcule le score de vitalité culturelle pour un point et un rayon donnés.

    Args:
        lat:      Latitude WGS84
        lon:      Longitude WGS84
        radius_m: Rayon de recherche en mètres (défaut : 500m)

    Returns:
        dict avec score (0–100), nb_evenements, nb_culturels, détail scores
    """
    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM gold.score_vitalite_culturelle(:lat, :lon, :r)"),
            {"lat": lat, "lon": lon, "r": radius_m},
        ).fetchone()

    return {
        "lat":               lat,
        "lon":               lon,
        "radius_m":          radius_m,
        "score":             float(row.score),
        "nb_evenements":     int(row.nb_evenements),
        "nb_culturels":      int(row.nb_culturels),
        "nb_sport":          int(row.nb_sport),
        "nb_associations":   int(row.nb_associations),
        "score_evenements":  float(row.score_evenements),
        "score_culturels":   float(row.score_culturels),
        "score_sport":       float(row.score_sport),
        "score_associations":float(row.score_associations),
    }


def _sync_stats_to_mongo():
    """Copie les stats de référence Silver vers MongoDB Gold."""
    engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT categorie, total_paris, computed_at FROM silver.vitalite_stats_reference"
        )).fetchall()
    if rows:
        df = pd.DataFrame([{"categorie": r.categorie, "total_paris": r.total_paris,
                            "computed_at": str(r.computed_at)} for r in rows])
        load_to_mongo_gold(df, "vitalite_stats_reference")


def _sync_scores_to_mongo(radius_m: float = 1000.0):
    """Pré-calcule le score vitalité au centroïde de chaque arrondissement → MongoDB Gold."""
    from datetime import datetime, timezone
    engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT arrondissement, centroid_lat, centroid_lon "
            "FROM silver.canicule_par_arrondissement ORDER BY arrondissement"
        )).fetchall()

    if not rows:
        print("  [SKIP] silver.canicule_par_arrondissement vide — sync vitalité MongoDB ignorée")
        return

    computed_at = datetime.now(timezone.utc).isoformat()
    records = []
    for row in rows:
        try:
            result = compute(lat=row.centroid_lat, lon=row.centroid_lon, radius_m=radius_m)
            result["arrondissement"] = row.arrondissement
            result["computed_at"] = computed_at
            records.append(result)
        except Exception as e:
            print(f"  [WARN] {row.arrondissement} : {e}")

    if records:
        df = pd.DataFrame(records)
        load_to_mongo_gold(df, "vitalite_arrondissement")
        print(f"  → mongodb.paris_gold.vitalite_arrondissement : {len(records)} arrondissements")


def setup():
    """Installe la fonction SQL gold et synchronise les stats vers MongoDB."""
    _create_gold_function()
    _sync_stats_to_mongo()
    _sync_scores_to_mongo()


if __name__ == "__main__":
    setup()

    # Exemple : place de la République
    result = compute(lat=48.8674, lon=2.3633, radius_m=500)
    print("\nScore Vitalité Culturelle — place de la République (r=500m)")
    for k, v in result.items():
        print(f"  {k}: {v}")
