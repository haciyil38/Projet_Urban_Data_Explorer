"""
INDICATEUR — AccessScore
Gold → Fonction SQL gold.score_accessibilite_services(lat, lon, profile, radius_m)

Score 0-100 basé sur décroissance exponentielle de la distance au plus proche :
  25% — Commerces alimentaires  (λ = 1/230 m)
  30% — Médecins / centres santé (λ = 1/700 m)
  25% — Hôpitaux / urgences     (λ = 1/2300 m)
  20% — Écoles maternelles/élém. (λ = 1/350 m)

Profils de pondération : standard | famille | senior | actif
"""

from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import text
from pipeline.db import get_engine, init_schemas, load_to_mongo_gold
from pipeline.config import LAMBDA_ACCESS, WEIGHTS_ACCESS


_SQL_FUNCTION = f"""
CREATE OR REPLACE FUNCTION gold.score_accessibilite_services(
    p_lat      DOUBLE PRECISION,
    p_lon      DOUBLE PRECISION,
    p_profile  TEXT             DEFAULT 'standard',
    p_radius   DOUBLE PRECISION DEFAULT 1000.0
)
RETURNS TABLE(
    score                   DOUBLE PRECISION,
    distance_commerces_m    DOUBLE PRECISION,
    distance_medecins_m     DOUBLE PRECISION,
    distance_hopitaux_m     DOUBLE PRECISION,
    distance_ecoles_m       DOUBLE PRECISION,
    score_commerces         DOUBLE PRECISION,
    score_medecins          DOUBLE PRECISION,
    score_hopitaux          DOUBLE PRECISION,
    score_ecoles            DOUBLE PRECISION
) AS $$
DECLARE
    p_geom GEOMETRY := ST_SetSRID(ST_MakePoint(p_lon, p_lat), 4326);

    d_com DOUBLE PRECISION;
    d_med DOUBLE PRECISION;
    d_hop DOUBLE PRECISION;
    d_eco DOUBLE PRECISION;

    s_com DOUBLE PRECISION;
    s_med DOUBLE PRECISION;
    s_hop DOUBLE PRECISION;
    s_eco DOUBLE PRECISION;

    w_com DOUBLE PRECISION := {WEIGHTS_ACCESS['commerces']};
    w_med DOUBLE PRECISION := {WEIGHTS_ACCESS['medecins']};
    w_hop DOUBLE PRECISION := {WEIGHTS_ACCESS['hopitaux']};
    w_eco DOUBLE PRECISION := {WEIGHTS_ACCESS['ecoles']};

    total_w      DOUBLE PRECISION;
    final_score  DOUBLE PRECISION;
BEGIN
    -- Ajustement des poids selon le profil
    IF p_profile = 'famille' THEN
        w_eco := w_eco * 1.5;
        w_med := w_med * 0.8;
    ELSIF p_profile = 'senior' THEN
        w_med := w_med * 1.5;
        w_hop := w_hop * 1.2;
    ELSIF p_profile = 'actif' THEN
        w_com := w_com * 1.3;
        w_eco := w_eco * 0.5;
    END IF;

    -- Normalisation des poids
    total_w := w_com + w_med + w_hop + w_eco;
    w_com := w_com / total_w;
    w_med := w_med / total_w;
    w_hop := w_hop / total_w;
    w_eco := w_eco / total_w;

    -- Distances minimales en mètres
    SELECT COALESCE(MIN(ST_Distance(geom::geography, p_geom::geography)), 100000)
    INTO d_com FROM silver.access_points_commerces;

    SELECT COALESCE(MIN(ST_Distance(geom::geography, p_geom::geography)), 100000)
    INTO d_med FROM silver.access_points_medecins;

    SELECT COALESCE(MIN(ST_Distance(geom::geography, p_geom::geography)), 100000)
    INTO d_hop FROM silver.access_points_hopitaux;

    SELECT COALESCE(MIN(ST_Distance(geom::geography, p_geom::geography)), 100000)
    INTO d_eco FROM silver.access_points_ecoles;

    -- Score par catégorie (0 si hors rayon)
    s_com := CASE WHEN d_com <= p_radius THEN EXP(-{LAMBDA_ACCESS['commerces']} * d_com) ELSE 0 END;
    s_med := CASE WHEN d_med <= p_radius THEN EXP(-{LAMBDA_ACCESS['medecins']}  * d_med) ELSE 0 END;
    s_hop := CASE WHEN d_hop <= p_radius THEN EXP(-{LAMBDA_ACCESS['hopitaux']}  * d_hop) ELSE 0 END;
    s_eco := CASE WHEN d_eco <= p_radius THEN EXP(-{LAMBDA_ACCESS['ecoles']}    * d_eco) ELSE 0 END;

    final_score := (s_com * w_com + s_med * w_med + s_hop * w_hop + s_eco * w_eco) * 100;

    RETURN QUERY SELECT
        ROUND(final_score::NUMERIC, 2)::DOUBLE PRECISION,
        ROUND(d_com::NUMERIC, 1)::DOUBLE PRECISION,
        ROUND(d_med::NUMERIC, 1)::DOUBLE PRECISION,
        ROUND(d_hop::NUMERIC, 1)::DOUBLE PRECISION,
        ROUND(d_eco::NUMERIC, 1)::DOUBLE PRECISION,
        ROUND((s_com * 100)::NUMERIC, 2)::DOUBLE PRECISION,
        ROUND((s_med * 100)::NUMERIC, 2)::DOUBLE PRECISION,
        ROUND((s_hop * 100)::NUMERIC, 2)::DOUBLE PRECISION,
        ROUND((s_eco * 100)::NUMERIC, 2)::DOUBLE PRECISION;
END;
$$ LANGUAGE plpgsql;
"""


def _sync_scores_to_mongo(radius_m: float = 1000.0):
    """Pré-calcule l'AccessScore au centroïde de chaque arrondissement → MongoDB Gold."""
    engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT arrondissement, centroid_lat, centroid_lon "
            "FROM silver.canicule_par_arrondissement "
            "ORDER BY arrondissement"
        )).fetchall()

    if not rows:
        print("  [SKIP] silver.canicule_par_arrondissement vide — sync MongoDB ignorée")
        return

    computed_at = datetime.now(timezone.utc).isoformat()
    records = []
    for row in rows:
        try:
            result = compute(
                lat=row.centroid_lat,
                lon=row.centroid_lon,
                profile="standard",
                radius=radius_m,
            )
            result["arrondissement"] = row.arrondissement
            result["computed_at"]    = computed_at
            records.append(result)
        except Exception as e:
            print(f"  [WARN] {row.arrondissement} : {e}")

    if records:
        df = pd.DataFrame(records)
        load_to_mongo_gold(df, "access_par_arrondissement")
        print(f"  → mongodb.paris_gold.access_par_arrondissement : {len(records)} arrondissements")


def setup():
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS gold"))
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        conn.execute(text(_SQL_FUNCTION))
        conn.commit()
    print("  Fonction gold.score_accessibilite_services créée / mise à jour.")
    _sync_scores_to_mongo()


def compute(lat: float, lon: float, profile: str = "standard", radius: float = 1000.0) -> dict:
    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM gold.score_accessibilite_services(:lat, :lon, :profile, :radius)"),
            {"lat": lat, "lon": lon, "profile": profile.lower(), "radius": radius},
        ).fetchone()

    return {
        "lat":                   lat,
        "lon":                   lon,
        "profile":               profile,
        "radius":                radius,
        "score":                 round(row[0], 1),
        "distance_commerces_m":  round(row[1], 1),
        "distance_medecins_m":   round(row[2], 1),
        "distance_hopitaux_m":   round(row[3], 1),
        "distance_ecoles_m":     round(row[4], 1),
        "score_commerces":       round(row[5], 2),
        "score_medecins":        round(row[6], 2),
        "score_hopitaux":        round(row[7], 2),
        "score_ecoles":          round(row[8], 2),
    }


if __name__ == "__main__":
    init_schemas()
    setup()
    result = compute(48.8566, 2.3522, "standard", 1000)
    for k, v in result.items():
        print(f"  {k}: {v}")
