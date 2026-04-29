# =============================================================================
# INDICATEUR — Indice de Confort Caniculaire
# Gold → Fonction SQL gold.score_canicule(lat, lon, radius_m)
#
# Score 0-100 calculé à la demande par point GPS et rayon :
#   35% — Refuges frais dans le rayon (PostGIS ST_DWithin)
#   35% — Couverture arborée de l'arrondissement le plus proche
#   30% — LST estivale ERA5-Land Copernicus de l'arrondissement le plus proche
#          Si LST absente : redistribution 50/50.
# =============================================================================

from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import text
from pipeline.db import get_engine, init_schemas, load_to_mongo_gold


_SQL_FUNCTION = """
CREATE OR REPLACE FUNCTION gold.score_canicule(
    p_lat    FLOAT,
    p_lon    FLOAT,
    p_radius FLOAT
)
RETURNS TABLE(
    lat                 FLOAT,
    lon                 FLOAT,
    radius_m            FLOAT,
    score               FLOAT,
    nb_refuges          INT,
    nb_fontaines        INT,
    nb_ilots_equip      INT,
    nb_espaces_verts    INT,
    nb_arbres           INT,
    circ_moy_cm         FLOAT,
    lst_ete_moy_c       FLOAT,
    score_refuges       FLOAT,
    score_arboree       FLOAT,
    score_lst           FLOAT
) AS $$
DECLARE
    ref_geo     GEOGRAPHY := ST_SetSRID(ST_MakePoint(p_lon, p_lat), 4326)::GEOGRAPHY;

    v_nb_refuges       INT   := 0;
    v_nb_fontaines     INT   := 0;
    v_nb_ilots_equip   INT   := 0;
    v_nb_espaces_verts INT   := 0;

    v_nb_arbres    FLOAT := 0;
    v_circ_moy_cm  FLOAT := 50;
    v_surface_m2   FLOAT := 500000;
    v_lst          FLOAT := NULL;

    -- Références Paris (normalisations)
    v_total_refuges  INT;
    v_paris_surface  FLOAT;
    v_max_densite    FLOAT;
    v_lst_min        FLOAT;
    v_lst_max        FLOAT;

    v_score_refuges  FLOAT;
    v_score_arboree  FLOAT;
    v_score_lst      FLOAT;
    v_score          FLOAT;

    circle_area FLOAT := PI() * p_radius * p_radius;
BEGIN
    -- ── Comptage refuges dans le rayon ────────────────────────────────────────
    SELECT
        COUNT(*),
        COUNT(*) FILTER (WHERE categorie = 'fontaine'),
        COUNT(*) FILTER (WHERE categorie = 'ilot_equip'),
        COUNT(*) FILTER (WHERE categorie = 'espace_vert')
    INTO v_nb_refuges, v_nb_fontaines, v_nb_ilots_equip, v_nb_espaces_verts
    FROM silver.canicule_refuges
    WHERE ST_DWithin(geom::GEOGRAPHY, ref_geo, p_radius);

    -- ── Données arboricoles et LST de l'arrondissement le plus proche ─────────
    SELECT a.nb_arbres, a.circ_moy_cm, a.surface_m2, a.lst_ete_moy_c
    INTO v_nb_arbres, v_circ_moy_cm, v_surface_m2, v_lst
    FROM silver.canicule_par_arrondissement a
    ORDER BY ST_Distance(
        ST_SetSRID(ST_MakePoint(a.centroid_lon, a.centroid_lat), 4326)::GEOGRAPHY,
        ref_geo
    )
    LIMIT 1;

    -- ── Références Paris pour normalisation ───────────────────────────────────
    -- Nombre total de refuges Paris
    SELECT COUNT(*) INTO v_total_refuges FROM silver.canicule_refuges;
    -- Surface totale Paris (m²)
    SELECT SUM(b.surface_m2) INTO v_paris_surface FROM silver.canicule_par_arrondissement b;
    -- Densité arborée max Paris
    SELECT MAX(b.nb_arbres * b.circ_moy_cm / NULLIF(b.surface_m2, 0))
    INTO v_max_densite FROM silver.canicule_par_arrondissement b;
    -- LST min/max Paris
    SELECT MIN(b.lst_ete_moy_c), MAX(b.lst_ete_moy_c)
    INTO v_lst_min, v_lst_max FROM silver.canicule_par_arrondissement b WHERE b.lst_ete_moy_c IS NOT NULL;

    -- ── Score refuges ─────────────────────────────────────────────────────────
    -- Comparaison au nombre attendu selon densité Paris × surface du cercle
    DECLARE
        expected_refuges FLOAT := GREATEST(0.01,
            (v_total_refuges::FLOAT / NULLIF(v_paris_surface, 0)) * circle_area
        );
    BEGIN
        v_score_refuges := LEAST(100, (v_nb_refuges::FLOAT / expected_refuges) * 50);
    END;

    -- ── Score arboré ─────────────────────────────────────────────────────────
    IF v_max_densite IS NOT NULL AND v_max_densite > 0 THEN
        v_score_arboree := LEAST(100,
            (v_nb_arbres * v_circ_moy_cm / NULLIF(v_surface_m2, 0)) / v_max_densite * 100
        );
    ELSE
        v_score_arboree := 0;
    END IF;

    -- ── Score LST ─────────────────────────────────────────────────────────────
    IF v_lst IS NOT NULL AND v_lst_max > v_lst_min THEN
        -- Inversé : plus frais = meilleur score
        v_score_lst := (v_lst_max - v_lst) / (v_lst_max - v_lst_min) * 100;
    ELSE
        v_score_lst := NULL;
    END IF;

    -- ── Score final ───────────────────────────────────────────────────────────
    IF v_score_lst IS NOT NULL THEN
        v_score := ROUND((v_score_refuges * 0.35 + v_score_arboree * 0.35 + v_score_lst * 0.30)::NUMERIC, 2);
    ELSE
        v_score := ROUND((v_score_refuges * 0.50 + v_score_arboree * 0.50)::NUMERIC, 2);
    END IF;

    RETURN QUERY SELECT
        p_lat, p_lon, p_radius,
        v_score,
        v_nb_refuges, v_nb_fontaines, v_nb_ilots_equip, v_nb_espaces_verts,
        v_nb_arbres::INT, v_circ_moy_cm,
        v_lst,
        ROUND(v_score_refuges::NUMERIC, 2)::FLOAT,
        ROUND(v_score_arboree::NUMERIC, 2)::FLOAT,
        ROUND(COALESCE(v_score_lst, 0)::NUMERIC, 2)::FLOAT;
END;
$$ LANGUAGE plpgsql;
"""


def _sync_scores_to_mongo(radius_m: float = 1000.0):
    """Pré-calcule le score canicule au centroïde de chaque arrondissement → MongoDB Gold."""
    engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT arrondissement, centroid_lat, centroid_lon "
            "FROM silver.canicule_par_arrondissement ORDER BY arrondissement"
        )).fetchall()

    if not rows:
        print("  [SKIP] silver.canicule_par_arrondissement vide — sync MongoDB ignorée")
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
        load_to_mongo_gold(df, "canicule_arrondissement")
        print(f"  → mongodb.paris_gold.canicule_arrondissement : {len(records)} arrondissements")


def setup():
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS gold"))
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        conn.execute(text(_SQL_FUNCTION))
        conn.commit()
    print("  Fonction gold.score_canicule créée / mise à jour.")
    _sync_scores_to_mongo()


def compute(lat: float, lon: float, radius_m: float) -> dict:
    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM gold.score_canicule(:lat, :lon, :r)"),
            {"lat": lat, "lon": lon, "r": radius_m},
        ).mappings().fetchone()
    if row is None:
        raise ValueError("gold.score_canicule n'a retourné aucune ligne")
    return dict(row)


if __name__ == "__main__":
    init_schemas()
    setup()
    result = compute(48.8566, 2.3522, 500)
    for k, v in result.items():
        print(f"  {k}: {v}")
