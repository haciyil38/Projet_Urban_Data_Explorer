# =============================================================================
# TRANSFORMATION — Indicateur Immobilier Paris
# Silver : agrégation par arrondissement + année
#
# Tables produites :
#   silver.immo_prix_m2          → prix m² médian par arrondissement et année
#   silver.immo_logements_sociaux → part HLM par arrondissement
#   silver.immo_revenus          → revenu médian par arrondissement (pivot)
#   silver.immo_accessibilite    → ratio prix_m2 / revenu_median
# =============================================================================

import pandas as pd
from pipeline.db import get_engine, read_mongo_bronze, load_to_silver


def build_silver_prix_m2() -> pd.DataFrame:
    """
    Calcule le prix au m² médian par arrondissement et par année.
    Filtre les transactions aberrantes (surface < 9m² ou > 500m², prix < 1000€/m²).
    """
    df = read_mongo_bronze("dvf_paris")

    df["valeur_fonciere"]     = pd.to_numeric(df["valeur_fonciere"],     errors="coerce")
    df["surface_reelle_bati"] = pd.to_numeric(df["surface_reelle_bati"], errors="coerce")

    # Exclure valeurs aberrantes
    df = df.dropna(subset=["valeur_fonciere", "surface_reelle_bati"])
    df = df[df["surface_reelle_bati"].between(9, 500)]
    df = df[df["valeur_fonciere"] > 0]

    df["prix_m2"] = df["valeur_fonciere"] / df["surface_reelle_bati"]
    df = df[df["prix_m2"].between(1_000, 50_000)]   # seuils Paris réalistes

    agg = (
        df.groupby(["code_commune", "annee"])
        .agg(
            prix_m2_median  =("prix_m2",           "median"),
            prix_m2_moyen   =("prix_m2",            "mean"),
            nb_transactions =("prix_m2",            "count"),
            surface_mediane =("surface_reelle_bati", "median"),
        )
        .round(2)
        .reset_index()
        .rename(columns={"code_commune": "code_insee"})
    )

    load_to_silver(agg, "immo_prix_m2")
    print(f"    {len(agg)} lignes (arrondissement × année)")
    return agg


def build_silver_logements_sociaux() -> pd.DataFrame:
    """
    Calcule la part de logements sociaux par arrondissement.
    Source : RPLS — 1 ligne = 1 logement social.
    Numérateur  : nb logements sociaux RPLS par arrondissement.
    Dénominateur: nb total logements estimé depuis DVF (proxy) ou INSEE RP.
    """
    df = read_mongo_bronze("logements_sociaux")

    # Arrondissement depuis DEPCOM (ex: "75101")
    df["code_insee"] = df["DEPCOM"].astype(str).str.strip()
    df = df[df["code_insee"].str.match(r"^751\d{2}$")]

    df["SURFHAB"] = pd.to_numeric(df["SURFHAB"], errors="coerce")
    df["NBPIECE"] = pd.to_numeric(df["NBPIECE"], errors="coerce")

    agg = (
        df.groupby("code_insee")
        .agg(
            nb_logements_sociaux=("code_insee",  "count"),
            surface_mediane_hlm =("SURFHAB",     "median"),
            nb_pieces_median_hlm=("NBPIECE",     "median"),
        )
        .round(2)
        .reset_index()
    )

    # Répartition par type de financement
    if "FINAN_CODE" in df.columns:
        fin = (
            df.groupby(["code_insee", "FINAN_CODE"])
            .size()
            .unstack(fill_value=0)
            .reset_index()
        )
        fin.columns = ["code_insee"] + [f"finan_{c}" for c in fin.columns[1:]]
        agg = agg.merge(fin, on="code_insee", how="left")

    load_to_silver(agg, "immo_logements_sociaux")
    print(f"    {len(agg)} arrondissements avec logements sociaux")
    return agg


def build_silver_revenus() -> pd.DataFrame:
    """
    Pivote les données Filosofi : 1 ligne par arrondissement
    avec colonnes revenu_median, d1 (bas revenus), d9 (hauts revenus).
    """
    df = read_mongo_bronze("revenus_insee")

    df["OBS_VALUE"] = pd.to_numeric(df["OBS_VALUE"], errors="coerce")

    pivot = (
        df.pivot_table(
            index="GEO",
            columns="FILOSOFI_MEASURE",
            values="OBS_VALUE",
            aggfunc="first",
        )
        .reset_index()
        .rename(columns={
            "GEO":    "code_insee",
            "MED_SL": "revenu_median",
            "D1_SL":  "revenu_d1",
            "D9_SL":  "revenu_d9",
        })
    )

    load_to_silver(pivot, "immo_revenus")
    print(f"    {len(pivot)} arrondissements avec données revenus")
    return pivot


def build_silver_accessibilite(
    df_prix: pd.DataFrame,
    df_revenus: pd.DataFrame,
) -> pd.DataFrame:
    """
    Calcule le ratio d'accessibilité : prix_m2_median / revenu_median_mensuel.
    Un ratio de 1.0 = 1 mois de revenu médian pour 1 m².
    On prend le prix de l'année la plus récente disponible par arrondissement.
    """
    # Prix le plus récent par arrondissement
    prix_recents = (
        df_prix.sort_values("annee", ascending=False)
        .groupby("code_insee")
        .first()
        .reset_index()
        [["code_insee", "prix_m2_median", "annee"]]
    )

    df = prix_recents.merge(df_revenus[["code_insee", "revenu_median"]], on="code_insee", how="inner")

    # Revenu mensuel = revenu annuel / 12
    df["revenu_mensuel"] = df["revenu_median"] / 12
    df["ratio_accessibilite"] = (df["prix_m2_median"] / df["revenu_mensuel"]).round(2)

    load_to_silver(df, "immo_accessibilite")
    print(f"    {len(df)} arrondissements avec ratio accessibilité")
    return df


def run():
    print("Silver [1/4] Prix m² par arrondissement et année...")
    df_prix = build_silver_prix_m2()

    print("Silver [2/4] Logements sociaux...")
    build_silver_logements_sociaux()

    print("Silver [3/4] Revenus médians...")
    df_revenus = build_silver_revenus()

    print("Silver [4/4] Accessibilité prix/revenus...")
    build_silver_accessibilite(df_prix, df_revenus)

    print("\nTransformation Silver immobilier terminée.")


if __name__ == "__main__":
    run()
