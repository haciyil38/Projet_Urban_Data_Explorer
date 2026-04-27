# =============================================================================
# INDICATEUR — Immobilier Paris
# Gold : scores et données agrégées par arrondissement
#
# Tables produites :
#   gold.immo_arrondissement → score + métriques par arrondissement (dernière année)
#   gold.immo_evolution      → série temporelle prix m² par arrondissement
# =============================================================================

import json
from datetime import datetime, timezone

import pandas as pd
from pipeline.db import read_silver, load_to_mongo_gold


def _normalize(series: pd.Series) -> pd.Series:
    mn, mx = series.min(), series.max()
    if mx == mn:
        return pd.Series(50.0, index=series.index)
    return (series - mn) / (mx - mn) * 100


def compute_gold_arrondissement() -> pd.DataFrame:
    """
    Construit la table gold par arrondissement avec :
    - prix_m2_median (dernière année)
    - evolution_1an : variation % prix m² sur 1 an
    - nb_logements_sociaux + part estimée
    - revenu_median
    - ratio_accessibilite
    - score global 0-100
    """
    df_prix    = read_silver("immo_prix_m2")
    df_social  = read_silver("immo_logements_sociaux")
    df_revenus = read_silver("immo_revenus")
    df_access  = read_silver("immo_accessibilite")

    # Prix dernière année disponible par arrondissement
    derniere_annee = df_prix["annee"].max()
    annee_precedente = derniere_annee - 1

    prix_n  = df_prix[df_prix["annee"] == derniere_annee][["code_insee", "prix_m2_median", "nb_transactions"]].copy()
    prix_n1 = df_prix[df_prix["annee"] == annee_precedente][["code_insee", "prix_m2_median"]].copy()
    prix_n1 = prix_n1.rename(columns={"prix_m2_median": "prix_m2_median_n1"})

    df = prix_n.merge(prix_n1, on="code_insee", how="left")
    df["evolution_1an_pct"] = (
        (df["prix_m2_median"] - df["prix_m2_median_n1"]) / df["prix_m2_median_n1"] * 100
    ).round(2)

    # Joindre logements sociaux
    df = df.merge(
        df_social[["code_insee", "nb_logements_sociaux", "surface_mediane_hlm"]],
        on="code_insee", how="left"
    )

    # Joindre revenus
    df = df.merge(
        df_revenus[["code_insee", "revenu_median", "revenu_d1", "revenu_d9"]],
        on="code_insee", how="left"
    )

    # Joindre accessibilité
    df = df.merge(
        df_access[["code_insee", "ratio_accessibilite"]],
        on="code_insee", how="left"
    )

    df = df.fillna(0)

    # Score global (0–100) :
    # - accessibilité inversée (plus c'est cher vs revenus, moins c'est accessible)
    # - prix inversé (moins c'est cher, plus accessible)
    # - logements sociaux : plus il y en a, meilleure la mixité sociale
    df["score_accessibilite"] = 100 - _normalize(df["ratio_accessibilite"])
    df["score_prix"]          = 100 - _normalize(df["prix_m2_median"])
    df["score_social"]        = _normalize(df["nb_logements_sociaux"])

    df["score"] = (
        df["score_accessibilite"] * 0.45 +
        df["score_prix"]          * 0.35 +
        df["score_social"]        * 0.20
    ).round(2)

    def build_details(row):
        return json.dumps({
            "prix_m2_median":      round(float(row["prix_m2_median"]), 2),
            "evolution_1an_pct":   round(float(row["evolution_1an_pct"]), 2),
            "nb_transactions":     int(row["nb_transactions"]),
            "nb_logements_sociaux":int(row["nb_logements_sociaux"]),
            "revenu_median":       int(row["revenu_median"]),
            "ratio_accessibilite": round(float(row["ratio_accessibilite"]), 2),
            "score_accessibilite": round(float(row["score_accessibilite"]), 2),
            "score_prix":          round(float(row["score_prix"]), 2),
            "score_social":        round(float(row["score_social"]), 2),
            "annee_reference":     int(derniere_annee),
        }, ensure_ascii=False)

    gold = pd.DataFrame({
        "code_insee":          df["code_insee"],
        "score":               df["score"],
        "prix_m2_median":      df["prix_m2_median"].round(2),
        "evolution_1an_pct":   df["evolution_1an_pct"],
        "nb_logements_sociaux":df["nb_logements_sociaux"].astype(int),
        "revenu_median":       df["revenu_median"].astype(int),
        "ratio_accessibilite": df["ratio_accessibilite"],
        "details":             df.apply(build_details, axis=1),
        "computed_at":         datetime.now(timezone.utc).isoformat(),
    })

    load_to_mongo_gold(gold, "immo_arrondissement")

    print(f"\nGold immobilier — {len(gold)} arrondissements (année réf. {derniere_annee})")
    print(gold[["code_insee", "score", "prix_m2_median", "evolution_1an_pct", "ratio_accessibilite"]]
          .sort_values("score", ascending=False)
          .to_string(index=False))

    return gold


def compute_gold_evolution() -> pd.DataFrame:
    """
    Série temporelle prix m² par arrondissement — pour la timeline du dashboard.
    """
    df = read_silver("immo_prix_m2")

    gold = df[["code_insee", "annee", "prix_m2_median", "nb_transactions"]].copy()
    gold["computed_at"] = datetime.now(timezone.utc).isoformat()

    load_to_mongo_gold(gold, "immo_evolution")
    print(f"\nGold évolution — {len(gold)} lignes (arrondissement × année)")
    return gold


def compute():
    compute_gold_arrondissement()
    compute_gold_evolution()


if __name__ == "__main__":
    compute()
