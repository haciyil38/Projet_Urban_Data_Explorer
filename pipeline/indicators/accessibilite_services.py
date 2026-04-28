"""
INDICATEUR — AccessScore
Gold : calcul a la demande pour un point (lat, lon) avec distance decay.
"""

from sqlalchemy import text

from pipeline.config import LAMBDA_ACCESS, WEIGHTS_ACCESS
from pipeline.db import get_engine


def _create_gold_function():
    sql = f"""
    CREATE OR REPLACE FUNCTION gold.score_accessibilite_services(
        p_lat DOUBLE PRECISION,
        p_lon DOUBLE PRECISION,
        p_profile TEXT DEFAULT 'standard'
    )
    RETURNS TABLE (
        score DOUBLE PRECISION,
        distance_commerces_m DOUBLE PRECISION,
        distance_medecins_m DOUBLE PRECISION,
        distance_hopitaux_m DOUBLE PRECISION,
        distance_ecoles_m DOUBLE PRECISION,
        score_commerces DOUBLE PRECISION,
        score_medecins DOUBLE PRECISION,
        score_hopitaux DOUBLE PRECISION,
        score_ecoles DOUBLE PRECISION
    )
    LANGUAGE plpgsql
    AS $$
    DECLARE
        pt GEOGRAPHY := ST_SetSRID(ST_MakePoint(p_lon, p_lat), 4326)::GEOGRAPHY;
        d_com DOUBLE PRECISION;
        d_med DOUBLE PRECISION;
        d_hop DOUBLE PRECISION;
        d_eco DOUBLE PRECISION;
        s_com DOUBLE PRECISION;
        s_med DOUBLE PRECISION;
        s_hop DOUBLE PRECISION;
        s_eco DOUBLE PRECISION;
        s_total DOUBLE PRECISION;
        w_com DOUBLE PRECISION := {WEIGHTS_ACCESS["commerces"]};
        w_med DOUBLE PRECISION := {WEIGHTS_ACCESS["medecins"]};
        w_hop DOUBLE PRECISION := {WEIGHTS_ACCESS["hopitaux"]};
        w_eco DOUBLE PRECISION := {WEIGHTS_ACCESS["ecoles"]};
    BEGIN
        IF lower(p_profile) = 'famille' THEN
            w_com := 0.20; w_med := 0.25; w_hop := 0.20; w_eco := 0.35;
        ELSIF lower(p_profile) = 'senior' THEN
            w_com := 0.15; w_med := 0.40; w_hop := 0.30; w_eco := 0.15;
        ELSIF lower(p_profile) = 'actif' THEN
            w_com := 0.35; w_med := 0.30; w_hop := 0.30; w_eco := 0.05;
        END IF;

        SELECT COALESCE(MIN(ST_Distance(geom::GEOGRAPHY, pt)), 100000.0)
          INTO d_com FROM silver.access_points_commerces;
        SELECT COALESCE(MIN(ST_Distance(geom::GEOGRAPHY, pt)), 100000.0)
          INTO d_med FROM silver.access_points_medecins;
        SELECT COALESCE(MIN(ST_Distance(geom::GEOGRAPHY, pt)), 100000.0)
          INTO d_hop FROM silver.access_points_hopitaux;
        SELECT COALESCE(MIN(ST_Distance(geom::GEOGRAPHY, pt)), 100000.0)
          INTO d_eco FROM silver.access_points_ecoles;

        s_com := exp(-{LAMBDA_ACCESS["commerces"]} * d_com);
        s_med := exp(-{LAMBDA_ACCESS["medecins"]} * d_med);
        s_hop := exp(-{LAMBDA_ACCESS["hopitaux"]} * d_hop);
        s_eco := exp(-{LAMBDA_ACCESS["ecoles"]} * d_eco);

        s_total := ROUND((
            s_com * w_com +
            s_med * w_med +
            s_hop * w_hop +
            s_eco * w_eco
        )::NUMERIC * 100.0, 2);

        RETURN QUERY
        SELECT
            s_total,
            ROUND(d_com::NUMERIC, 2)::DOUBLE PRECISION,
            ROUND(d_med::NUMERIC, 2)::DOUBLE PRECISION,
            ROUND(d_hop::NUMERIC, 2)::DOUBLE PRECISION,
            ROUND(d_eco::NUMERIC, 2)::DOUBLE PRECISION,
            ROUND(s_com::NUMERIC, 4)::DOUBLE PRECISION,
            ROUND(s_med::NUMERIC, 4)::DOUBLE PRECISION,
            ROUND(s_hop::NUMERIC, 4)::DOUBLE PRECISION,
            ROUND(s_eco::NUMERIC, 4)::DOUBLE PRECISION;
    END;
    $$;
    """
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(text(sql))
        conn.commit()
    print("  Fonction gold.score_accessibilite_services creee.")


def compute(lat: float, lon: float, profile: str = "standard") -> dict:
    # Normalisation du profil en minuscules
    profile = profile.lower()
    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM gold.score_accessibilite_services(:lat, :lon, :profile)"),
            {"lat": lat, "lon": lon, "profile": profile},
        ).fetchone()

    return {
        "lat": lat,
        "lon": lon,
        "profile": profile,
        "score": float(row.score),
        "distance_commerces_m": float(row.distance_commerces_m),
        "distance_medecins_m": float(row.distance_medecins_m),
        "distance_hopitaux_m": float(row.distance_hopitaux_m),
        "distance_ecoles_m": float(row.distance_ecoles_m),
        "score_commerces": float(row.score_commerces),
        "score_medecins": float(row.score_medecins),
        "score_hopitaux": float(row.score_hopitaux),
        "score_ecoles": float(row.score_ecoles),
    }


def setup():
    _create_gold_function()


if __name__ == "__main__":
    setup()
    result = compute(lat=48.8566, lon=2.3522, profile="standard")
    print(result)
