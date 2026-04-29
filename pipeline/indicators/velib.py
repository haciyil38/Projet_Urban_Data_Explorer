# =============================================================================
# INDICATEUR — Vélib / Mobilité douce
# Gold : score calculé à la demande pour un point (lat, lon) et un rayon
#
# Score = 0.5 × score_densité + 0.5 × score_disponibilité
#
#   score_densité    = min(100, nb_stations_rayon / nb_attendu × 50)
#     nb_attendu     = total_stations × (π·r²) / surface_metropole
#     → 50 = densité égale à la moyenne métropole Vélib
#     → 100 = double de la densité moyenne
#
#   score_disponibilité = avg(taux_disponibilite) × 100
#     → 100 = toutes les bornes ont des vélos
#     → 50  = moitié des vélos disponibles en moyenne
# =============================================================================

from sqlalchemy import text
from pipeline.db import get_engine

# Surface approximative de la zone métropole couverte par Vélib (~750 km²)
METRO_AREA_M2 = 750_000_000.0


def _create_gold_function():
    """Crée ou remplace la fonction SQL gold.score_velib."""
    sql = f"""
    CREATE OR REPLACE FUNCTION gold.score_velib(
        p_lat      DOUBLE PRECISION,
        p_lon      DOUBLE PRECISION,
        p_radius_m DOUBLE PRECISION DEFAULT 500
    )
    RETURNS TABLE (
        score               DOUBLE PRECISION,
        nb_stations         BIGINT,
        total_velos_dispo   BIGINT,
        total_velos_meca    BIGINT,
        total_velos_elec    BIGINT,
        total_bornes_dispo  BIGINT,
        taux_moyen          DOUBLE PRECISION,
        score_densite       DOUBLE PRECISION,
        score_disponibilite DOUBLE PRECISION,
        radius_m            DOUBLE PRECISION
    )
    LANGUAGE plpgsql
    AS $$
    DECLARE
        pt             GEOMETRY  := ST_SetSRID(ST_MakePoint(p_lon, p_lat), 4326);
        pt_geog        GEOGRAPHY := pt::GEOGRAPHY;
        area_m2        DOUBLE PRECISION := pi() * p_radius_m * p_radius_m;
        metro_area     DOUBLE PRECISION := {METRO_AREA_M2};

        total_stations BIGINT;
        cnt_stations   BIGINT;
        sum_velos      BIGINT;
        sum_meca       BIGINT;
        sum_elec       BIGINT;
        sum_bornes     BIGINT;
        avg_taux       DOUBLE PRECISION;
        expected       DOUBLE PRECISION;
        s_dens         DOUBLE PRECISION;
        s_dispo        DOUBLE PRECISION;
        s_total        DOUBLE PRECISION;
    BEGIN
        -- Total stations installées dans la métropole
        SELECT COUNT(*) INTO total_stations
        FROM silver.velib_stations
        WHERE is_installed = TRUE;

        -- Agrégats dans le rayon
        SELECT
            COUNT(*),
            COALESCE(SUM(num_velos_dispo), 0),
            COALESCE(SUM(num_velos_meca),  0),
            COALESCE(SUM(num_velos_elec),  0),
            COALESCE(SUM(num_bornes_dispo), 0),
            COALESCE(AVG(taux_disponibilite), 0)
        INTO cnt_stations, sum_velos, sum_meca, sum_elec, sum_bornes, avg_taux
        FROM silver.velib_stations
        WHERE is_installed = TRUE
          AND ST_DWithin(geom::GEOGRAPHY, pt_geog, p_radius_m);

        -- Score densité : 50 = densité moyenne métropole
        IF total_stations > 0 THEN
            expected := total_stations::DOUBLE PRECISION * area_m2 / metro_area;
            s_dens   := LEAST(100.0, CASE WHEN expected > 0
                             THEN cnt_stations::DOUBLE PRECISION / expected * 50.0
                             ELSE 0.0 END);
        ELSE
            s_dens := 0.0;
        END IF;

        -- Score disponibilité : taux moyen × 100
        s_dispo := LEAST(100.0, avg_taux * 100.0);

        -- Score final pondéré
        s_total := 0.5 * s_dens + 0.5 * s_dispo;

        RETURN QUERY SELECT
            ROUND(s_total::NUMERIC, 2)::DOUBLE PRECISION,
            cnt_stations,
            sum_velos,
            sum_meca,
            sum_elec,
            sum_bornes,
            ROUND(avg_taux::NUMERIC, 4)::DOUBLE PRECISION,
            ROUND(s_dens::NUMERIC, 2)::DOUBLE PRECISION,
            ROUND(s_dispo::NUMERIC, 2)::DOUBLE PRECISION,
            p_radius_m;
    END;
    $$;
    """
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS gold"))
        conn.execute(text(sql))
        conn.commit()
    print("  Fonction gold.score_velib créée / mise à jour.")


def compute(lat: float, lon: float, radius_m: float = 500) -> dict:
    """Calcule le score Vélib pour un point (lat, lon) dans un rayon donné."""
    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM gold.score_velib(:lat, :lon, :r)"),
            {"lat": lat, "lon": lon, "r": radius_m},
        ).mappings().fetchone()

    if row is None:
        raise ValueError("La fonction gold.score_velib n'a retourné aucune ligne.")

    return {
        "lat":               lat,
        "lon":               lon,
        "radius_m":          radius_m,
        "score":             float(row["score"]),
        "nb_stations":       int(row["nb_stations"]),
        "total_velos_dispo": int(row["total_velos_dispo"]),
        "total_velos_meca":  int(row["total_velos_meca"]),
        "total_velos_elec":  int(row["total_velos_elec"]),
        "total_bornes_dispo":int(row["total_bornes_dispo"]),
        "taux_moyen":        float(row["taux_moyen"]),
        "score_densite":     float(row["score_densite"]),
        "score_disponibilite": float(row["score_disponibilite"]),
    }


def setup():
    """Crée la fonction gold si elle n'existe pas encore (appelé au démarrage de l'API)."""
    _create_gold_function()


def run():
    print("=== INDICATEUR VÉLIB ===")
    _create_gold_function()

    # Test : place de la République
    result = compute(lat=48.8671, lon=2.3631, radius_m=500)
    print(
        f"  Test République → score={result['score']}, "
        f"stations={result['nb_stations']}, "
        f"vélos={result['total_velos_dispo']} "
        f"(meca={result['total_velos_meca']}, elec={result['total_velos_elec']})"
    )
    print("=== INDICATEUR VÉLIB TERMINÉ ===")


if __name__ == "__main__":
    run()
