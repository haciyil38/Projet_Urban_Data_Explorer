# =============================================================================
# INGESTION — Indicateur Immobilier Paris
# Bronze : données brutes depuis les APIs open data
#
# Sources :
#   [1] DVF+ (CEREMA) — transactions immobilières 2014–2024
#       https://apidf-preprod.cerema.fr/dvf_opendata/mutations/
#   [2] RPLS (data.gouv.fr) — logements sociaux Paris
#   [3] INSEE Filosofi — revenus médians par arrondissement
# =============================================================================

import io
import zipfile
from pathlib import Path

import pandas as pd
import requests

from pipeline.db import init_schemas, load_to_bronze

_BRONZE_DIR = Path(__file__).parents[2] / "data" / "bronze"

# Codes INSEE des 20 arrondissements parisiens (75101 … 75120)
_ARRONDISSEMENTS_INSEE = [f"751{str(i).zfill(2)}" for i in range(1, 21)]

# CSV DVF par département sur data.gouv.fr — 1 fichier par année, stable
_DVF_BASE  = "https://files.data.gouv.fr/geo-dvf/latest/csv/{annee}/departements/75.csv.gz"
_DVF_YEARS = [2021, 2022, 2023, 2024, 2025]

# RPLS — API DiDo SDES (logements sociaux, France entière, filtre DEP_CODE=75)
_RPLS_URL = "https://data.statistiques.developpement-durable.gouv.fr/dido/api/v1/datafiles/f3c2f2cb-8fb1-40fd-8733-964247744c9a/csv"

# INSEE Filosofi 2021 — revenus médians par commune (géo 2025)
# Source : https://www.insee.fr/fr/statistiques/7756729
_FILOSOFI_URL = "https://www.insee.fr/fr/statistiques/fichier/7756729/base-cc-filosofi-2021-geo2025_csv.zip"


# =============================================================================
# [1] DVF — Transactions immobilières
# =============================================================================

def fetch_dvf() -> pd.DataFrame:
    """
    Télécharge les transactions DVF Paris depuis data.gouv.fr (CSV par année, département 75).
    Source : https://files.data.gouv.fr/geo-dvf/latest/csv/{annee}/departements/75.csv.gz
    Filtre : ventes de logements (appartements / maisons) sur les arrondissements parisiens.
    """
    cols_keep = [
        "id_mutation", "date_mutation", "nature_mutation", "valeur_fonciere",
        "code_postal", "code_commune", "type_local", "surface_reelle_bati",
        "nombre_pieces_principales", "longitude", "latitude",
    ]
    frames = []

    for annee in _DVF_YEARS:
        url = _DVF_BASE.format(annee=annee)
        print(f"    DVF {annee}...", end="\r")
        try:
            r = requests.get(url, timeout=120)
            r.raise_for_status()
        except requests.exceptions.RequestException as e:
            print(f"\n  [WARN] DVF {annee} non disponible : {e}")
            continue

        df = pd.read_csv(
            io.BytesIO(r.content),
            compression="gzip",
            dtype=str,
            low_memory=False,
        )

        # Filtrer Paris arrondissements + ventes de logements
        df = df[df["code_commune"].str.match(r"^751\d{2}$", na=False)]
        df = df[df["nature_mutation"] == "Vente"]
        df = df[df["type_local"].isin(["Appartement", "Maison"])]

        # Garder colonnes utiles
        existing = [c for c in cols_keep if c in df.columns]
        df = df[existing].copy()
        df["annee"] = annee

        frames.append(df)
        print(f"    DVF {annee} : {len(df)} transactions")

    if not frames:
        return pd.DataFrame()

    result = pd.concat(frames, ignore_index=True)
    print(f"    Total DVF : {len(result)} transactions (2020–2024)")
    return result


# =============================================================================
# [2] RPLS — Logements sociaux
# =============================================================================

def fetch_logements_sociaux() -> pd.DataFrame:
    """
    Télécharge le RPLS depuis l'API DiDo SDES (logements sociaux France entière).
    Filtre sur Paris (DEP_CODE = 75).
    Source : https://data.statistiques.developpement-durable.gouv.fr
    Colonnes utiles : DEPCOM (code INSEE arrondissement), SURFHAB, FINAN_CODE, CONSTRUCT, NBPIECE
    """
    local_file = _BRONZE_DIR / "rpls_logements_sociaux.csv"
    if local_file.exists():
        print(f"  Lecture locale RPLS ({local_file.name})...")
        source = local_file
    else:
        print("  Téléchargement RPLS (France entière, ~3 Go)...")
        try:
            r = requests.get(_RPLS_URL, timeout=300, stream=True)
            r.raise_for_status()
        except requests.exceptions.RequestException as e:
            print(f"  [WARN] RPLS non disponible : {e}")
            return pd.DataFrame()
        source = io.BytesIO(r.content)

    try:
        chunks = []
        for chunk in pd.read_csv(
            source,
            sep=";",
            encoding="utf-8-sig",
            dtype=str,
            low_memory=False,
            chunksize=100_000,
        ):
            paris = chunk[chunk["DEP_CODE"].astype(str).str.strip() == "75"]
            if not paris.empty:
                chunks.append(paris)

        if not chunks:
            print("  [WARN] Aucun logement social Paris trouvé")
            return pd.DataFrame()

        df = pd.concat(chunks, ignore_index=True)
    except Exception as e:
        print(f"  [WARN] Erreur lecture RPLS : {e}")
        return pd.DataFrame()

    print(f"    {len(df)} logements sociaux Paris")
    return df


# =============================================================================
# [3] INSEE Filosofi — Revenus médians par arrondissement
# =============================================================================

def fetch_revenus_insee() -> pd.DataFrame:
    """
    Télécharge les revenus médians par commune depuis INSEE Filosofi 2021.
    Filtre sur les arrondissements parisiens (75101–75120).
    Source : https://www.insee.fr/fr/statistiques/7756729
    Format : CSV pivot — GEO | FILOSOFI_MEASURE | OBS_VALUE
    Mesures retenues : MED_SL (médiane salaires), D1_SL (1er décile), D9_SL (9e décile)
    """
    print("  Téléchargement INSEE Filosofi (revenus)...")
    try:
        r = requests.get(_FILOSOFI_URL, timeout=120)
        r.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"  [WARN] INSEE Filosofi non disponible : {e}")
        return pd.DataFrame()

    try:
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            csv_name = next(
                n for n in z.namelist()
                if n.endswith(".csv") and "data" in n.lower() and "metadata" not in n.lower()
            )
            with z.open(csv_name) as f:
                df = pd.read_csv(f, sep=";", encoding="utf-8-sig", dtype=str, low_memory=False)
    except Exception as e:
        print(f"  [WARN] Erreur lecture Filosofi : {e}")
        return pd.DataFrame()

    df = df[df["GEO"].str.match(r"^751\d{2}$", na=False)]
    df = df[df["FILOSOFI_MEASURE"].isin(["MED_SL", "D1_SL", "D9_SL"])]

    print(f"    {len(df)} lignes revenus INSEE Paris")
    return df


# =============================================================================
# Run
# =============================================================================

def run():
    init_schemas()

    print("\n[1/3] DVF — Transactions immobilières")
    df = fetch_dvf()
    load_to_bronze(df, "dvf_paris")

    print("\n[2/3] RPLS — Logements sociaux")
    df = fetch_logements_sociaux()
    load_to_bronze(df, "logements_sociaux")

    print("\n[3/3] INSEE Filosofi — Revenus médians")
    df = fetch_revenus_insee()
    load_to_bronze(df, "revenus_insee")


if __name__ == "__main__":
    run()
