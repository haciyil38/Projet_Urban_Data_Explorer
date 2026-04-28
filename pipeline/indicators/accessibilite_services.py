"""
INDICATEUR — AccessScore (V3 - Radius Support)
Calcul du score final dans la couche Gold avec support du rayon.
"""

from sqlalchemy import text
from pipeline.db import get_engine
from pipeline.config import LAMBDA_ACCESS, WEIGHTS_ACCESS

def _init_gold_function():
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS gold"))
        
        # Fonction SQL pour calculer le score avec décroissance exponentielle et limite de rayon
        conn.execute(text(f"""
            CREATE OR REPLACE FUNCTION gold.score_accessibilite_services(
                target_lat DOUBLE PRECISION, 
                target_lon DOUBLE PRECISION, 
                profile TEXT,
                max_radius DOUBLE PRECISION DEFAULT 1000.0
            )
            RETURNS TABLE (
                score DOUBLE PRECISION,
                dist_com DOUBLE PRECISION,
                dist_med DOUBLE PRECISION,
                dist_hop DOUBLE PRECISION,
                dist_eco DOUBLE PRECISION,
                score_com DOUBLE PRECISION,
                score_med DOUBLE PRECISION,
                score_hop DOUBLE PRECISION,
                score_eco DOUBLE PRECISION
            ) AS $$
            DECLARE
                p_geom GEOMETRY := ST_SetSRID(ST_MakePoint(target_lon, target_lat), 4326);
                d_com DOUBLE PRECISION;
                d_med DOUBLE PRECISION;
                d_hop DOUBLE PRECISION;
                d_eco DOUBLE PRECISION;
                s_com DOUBLE PRECISION;
                s_med DOUBLE PRECISION;
                s_hop DOUBLE PRECISION;
                s_eco DOUBLE PRECISION;
                final_score DOUBLE PRECISION;
                w_com DOUBLE PRECISION;
                w_med DOUBLE PRECISION;
                w_hop DOUBLE PRECISION;
                w_eco DOUBLE PRECISION;
            BEGIN
                -- Récupération des poids selon le profil
                IF profile = 'famille' THEN
                    w_com := {WEIGHTS_ACCESS['famille']['commerces']};
                    w_med := {WEIGHTS_ACCESS['famille']['medecins']};
                    w_hop := {WEIGHTS_ACCESS['famille']['hopitaux']};
                    w_eco := {WEIGHTS_ACCESS['famille']['ecoles']};
                ELSIF profile = 'senior' THEN
                    w_com := {WEIGHTS_ACCESS['senior']['commerces']};
                    w_med := {WEIGHTS_ACCESS['senior']['medecins']};
                    w_hop := {WEIGHTS_ACCESS['senior']['hopitaux']};
                    w_eco := {WEIGHTS_ACCESS['senior']['ecoles']};
                ELSIF profile = 'actif' THEN
                    w_com := {WEIGHTS_ACCESS['actif']['commerces']};
                    w_med := {WEIGHTS_ACCESS['actif']['medecins']};
                    w_hop := {WEIGHTS_ACCESS['actif']['hopitaux']};
                    w_eco := {WEIGHTS_ACCESS['actif']['ecoles']};
                ELSE
                    w_com := {WEIGHTS_ACCESS['standard']['commerces']};
                    w_med := {WEIGHTS_ACCESS['standard']['medecins']};
                    w_hop := {WEIGHTS_ACCESS['standard']['hopitaux']};
                    w_eco := {WEIGHTS_ACCESS['standard']['ecoles']};
                END IF;

                -- Calcul des distances minimales (en metres)
                SELECT COALESCE(MIN(ST_Distance(geom::geography, p_geom::geography)), 100000) INTO d_com FROM silver.access_points_commerces;
                SELECT COALESCE(MIN(ST_Distance(geom::geography, p_geom::geography)), 100000) INTO d_med FROM silver.access_points_medecins;
                SELECT COALESCE(MIN(ST_Distance(geom::geography, p_geom::geography)), 100000) INTO d_hop FROM silver.access_points_hopitaux;
                SELECT COALESCE(MIN(ST_Distance(geom::geography, p_geom::geography)), 100000) INTO d_eco FROM silver.access_points_ecoles;

                -- Application du rayon : si distance > max_radius, le score de la categorie est 0
                s_com := CASE WHEN d_com <= max_radius THEN EXP(-{LAMBDA_ACCESS['commerces']} * d_com) ELSE 0 END;
                s_med := CASE WHEN d_med <= max_radius THEN EXP(-{LAMBDA_ACCESS['medecins']} * d_med) ELSE 0 END;
                s_hop := CASE WHEN d_hop <= max_radius THEN EXP(-{LAMBDA_ACCESS['hopitaux']} * d_hop) ELSE 0 END;
                s_eco := CASE WHEN d_eco <= max_radius THEN EXP(-{LAMBDA_ACCESS['ecoles']} * d_eco) ELSE 0 END;

                final_score := (s_com * w_com + s_med * w_med + s_hop * w_hop + s_eco * w_eco) * 100;

                RETURN QUERY SELECT final_score, d_com, d_med, d_hop, d_eco, s_com, s_med, s_hop, s_eco;
            END;
            $$ LANGUAGE plpgsql;
        """))
        conn.commit()
    print("  Fonction gold.score_accessibilite_services avec support rayon creee.")

def compute(lat: float, lon: float, profile: str = "standard", radius: float = 1000.0) -> dict:
    profile = profile.lower()
    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM gold.score_accessibilite_services(:lat, :lon, :profile, :radius)"),
            {"lat": lat, "lon": lon, "profile": profile, "radius": radius},
        ).fetchone()

    return {
        "lat": lat,
        "lon": lon,
        "profile": profile,
        "radius": radius,
        "score": round(row[0], 1),
        "distance_commerces_m": round(row[1], 1),
        "distance_medecins_m": round(row[2], 1),
        "distance_hopitaux_m": round(row[3], 1),
        "distance_ecoles_m": round(row[4], 1),
        "score_commerces": round(row[5], 4),
        "score_medecins": round(row[6], 4),
        "score_hopitaux": round(row[7], 4),
        "score_ecoles": round(row[8], 4),
    }

def run():
    _init_gold_function()

if __name__ == "__main__":
    run()
