# =============================================================================
# INDICATEUR — Indice de confort caniculaire
# =============================================================================

import pandas as pd
import geopandas as gpd
from pipeline.db import load_to_bronze, get_engine, load_to_gold
from pipeline.ingestion.paris_opendata import (
    ingest_ilots_equipements,
    ingest_ilots_espaces_verts,
    ingest_fontaines,
    ingest_arbres,
)
from pipeline.ingestion.demographics import (
    ingest_population_arrondissements,
    ingest_contours_arrondissements,
)
from pipeline.config import ARRONDISSEMENTS, WEIGHTS_CANICULAIRE
from datetime import datetime


def map_code_postal_to_arrondissement(code_postal):
    """Map code postal (75001-75020) to arrondissement INSEE code."""
    if pd.isna(code_postal):
        return None
    try:
        num = int(str(code_postal)[-2:])  # Extract last 2 digits
        if 1 <= num <= 20:
            return f"750{num:02d}"
    except (ValueError, TypeError):
        pass
    return None


def ingest_lst_arrondissements():
    """
    Placeholder for Land Surface Temperature data.
    In real implementation, fetch from Copernicus/Sentinel or weather APIs.
    Returns average summer LST per arrondissement.
    """
    # Placeholder: simulated data based on typical Paris LST patterns
    # Lower temperatures in greener/central areas
    lst_data = {
        'arrondissement': ARRONDISSEMENTS,
        'lst_estival_moy': [
            28.5, 29.0, 30.2, 29.8, 31.5, 30.8, 31.2, 30.5, 31.8, 32.1,
            32.3, 32.5, 32.8, 33.0, 33.2, 32.9, 32.7, 32.4, 32.1, 31.9
        ]
    }
    return pd.DataFrame(lst_data)


def calculate_indice_confort_caniculaire() -> pd.DataFrame:
    """
    Calcule l'indice de confort caniculaire par arrondissement.
    Dimensions :
    - Refuges frais (35%) : (équip + espaces verts frais + fontaines) / 1000 hab
    - Couverture arborée (35%) : densité arbres × circonférence moy / surface
    - Température surface (30%) : LST estivale moy (inversée)
    """

    # --- Chargement des données ---
    print("Chargement des données Paris OpenData...")
    df_equip = ingest_ilots_equipements()
    df_verts = ingest_ilots_espaces_verts()
    df_fontaines = ingest_fontaines()
    df_arbres = ingest_arbres()

    # Sauvegarde en bronze
    load_to_bronze(df_equip, "ilots_equipements")
    load_to_bronze(df_verts, "ilots_espaces_verts")
    load_to_bronze(df_fontaines, "fontaines")
    load_to_bronze(df_arbres, "arbres")

    # --- Chargement des données démographiques ---
    print("Chargement des données démographiques...")
    df_pop = ingest_population_arrondissements()
    df_contours = ingest_contours_arrondissements()
    df_lst = ingest_lst_arrondissements()

    # --- Agrégation par arrondissement ---
    print("Agrégation par arrondissement...")

    # Mapper code_postal vers arrondissement pour chaque dataset
    for df in [df_equip, df_verts, df_fontaines, df_arbres]:
        if 'code_postal' in df.columns:
            df['arrondissement'] = df['code_postal'].apply(map_code_postal_to_arrondissement)
        elif 'arrondissement' not in df.columns:
            print(f"Warning: no 'code_postal' or 'arrondissement' column in dataset")
            df['arrondissement'] = None

    # Refuges frais : combiner équipements, espaces verts, fontaines
    df_refuges = pd.concat([
        df_equip[['arrondissement']].dropna(),
        df_verts[['arrondissement']].dropna(),
        df_fontaines[['arrondissement']].dropna()
    ])
    nb_refuges = df_refuges.groupby('arrondissement').size().reset_index(name='nb_refuges')

    # Arbres : nombre et circonférence moyenne
    if 'circonference_cm' in df_arbres.columns:
        df_arbres_agg = df_arbres.groupby('arrondissement').agg(
            nb_arbres=('id', 'count'),
            circonference_moy=('circonference_cm', 'mean')
        ).reset_index()
    else:
        print("Warning: 'circonference_cm' column not found in arbres data")
        df_arbres_agg = df_arbres.groupby('arrondissement').agg(
            nb_arbres=('id', 'count')
        ).reset_index()
        df_arbres_agg['circonference_moy'] = 50  # Default value

    # Surfaces des arrondissements
    if not df_contours.empty and 'geometry' in df_contours.columns:
        df_contours = df_contours.to_crs(epsg=2154)  # Lambert 93 for area calculation
        df_contours['surface_m2'] = df_contours.geometry.area
        surfaces_arr = df_contours[['arrondissement', 'surface_m2']].copy()
    else:
        print("Warning: contours data not available, using placeholder surfaces")
        # Placeholder surfaces (approximate in m²)
        surfaces_data = {
            'arrondissement': ARRONDISSEMENTS,
            'surface_m2': [991000, 991000, 1173000, 1605000, 2539000, 2153000, 4090000, 3881000, 2178000, 2887000,
                          3665000, 16390000, 7146000, 5610000, 8460000, 7908000, 5669000, 9916000, 6792000, 5980000]
        }
        surfaces_arr = pd.DataFrame(surfaces_data)

    # --- Calculs des métriques brutes ---
    print("Calcul des métriques...")

    # Refuges par 1000 habitants
    nb_refuges_1k_hab = nb_refuges.merge(df_pop, on='arrondissement', how='left')
    nb_refuges_1k_hab['nb_refuges_1k_hab'] = nb_refuges_1k_hab['nb_refuges'] / (nb_refuges_1k_hab['population'] / 1000)

    # Densité arborée pondérée
    densite_arboree = df_arbres_agg.merge(surfaces_arr, on='arrondissement', how='left')
    densite_arboree['densite_arboree_ponderee'] = (densite_arboree['nb_arbres'] * densite_arboree['circonference_moy']) / densite_arboree['surface_m2']

    # LST (inversée : température plus basse = score plus élevé)
    df_lst['lst_score'] = 100 - ((df_lst['lst_estival_moy'] - df_lst['lst_estival_moy'].min()) / (df_lst['lst_estival_moy'].max() - df_lst['lst_estival_moy'].min()) * 100)

    # --- Normalisation 0-100 ---
    print("Normalisation des scores...")

    # Fonction de normalisation
    def normalize_series(series):
        if series.max() == series.min():
            return pd.Series([50.0] * len(series), index=series.index)
        return ((series - series.min()) / (series.max() - series.min()) * 100).round(2)

    # Normaliser chaque dimension
    nb_refuges_1k_hab['score_refuges'] = normalize_series(nb_refuges_1k_hab['nb_refuges_1k_hab'])
    densite_arboree['score_arboree'] = normalize_series(densite_arboree['densite_arboree_ponderee'])
    df_lst['score_lst'] = normalize_series(df_lst['lst_score'])

    # --- Score final pondéré ---
    print("Calcul du score final...")

    df_final = nb_refuges_1k_hab[['arrondissement', 'nb_refuges_1k_hab', 'score_refuges']].merge(
        densite_arboree[['arrondissement', 'nb_arbres', 'circonference_moy', 'densite_arboree_ponderee', 'score_arboree']],
        on='arrondissement',
        how='outer'
    ).merge(
        df_lst[['arrondissement', 'lst_estival_moy', 'score_lst']],
        on='arrondissement',
        how='outer'
    )

    # Remplir les NaN avec 0 pour les scores
    df_final['score_refuges'] = df_final['score_refuges'].fillna(0)
    df_final['score_arboree'] = df_final['score_arboree'].fillna(0)
    df_final['score_lst'] = df_final['score_lst'].fillna(0)

    # Score final
    df_final['score'] = (
        df_final['score_refuges'] * WEIGHTS_CANICULAIRE['refuges_frais'] +
        df_final['score_arboree'] * WEIGHTS_CANICULAIRE['couverture_arboree'] +
        df_final['score_lst'] * WEIGHTS_CANICULAIRE['lst']
    ).round(2)

    # Détails JSON
    df_final['details'] = df_final.apply(lambda row: {
        'refuges': {
            'nb_refuges_1k_hab': round(row['nb_refuges_1k_hab'], 2) if pd.notna(row['nb_refuges_1k_hab']) else None,
            'score': row['score_refuges']
        },
        'arbres': {
            'nb_arbres': int(row['nb_arbres']) if pd.notna(row['nb_arbres']) else 0,
            'circonference_moy': round(row['circonference_moy'], 2) if pd.notna(row['circonference_moy']) else None,
            'densite_arboree_ponderee': round(row['densite_arboree_ponderee'], 6) if pd.notna(row['densite_arboree_ponderee']) else None,
            'score': row['score_arboree']
        },
        'lst': {
            'lst_estival_moy': round(row['lst_estival_moy'], 2) if pd.notna(row['lst_estival_moy']) else None,
            'score': row['score_lst']
        }
    }, axis=1)

    # Timestamp
    df_final['computed_at'] = datetime.now()

    # Sélectionner les colonnes finales
    result_df = df_final[['arrondissement', 'score', 'details', 'computed_at']].copy()

    # Sauvegarde en gold
    load_to_gold(result_df, "indice_confort_caniculaire_arrondissement")

    print(f"Indice calculé pour {len(result_df)} arrondissements")
    return result_df


if __name__ == "__main__":
    df = calculate_indice_confort_caniculaire()
    print(df.head())