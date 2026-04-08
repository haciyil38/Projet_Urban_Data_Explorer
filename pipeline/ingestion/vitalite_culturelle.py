# =============================================================================
# INGESTION — Indice de Vitalité Culturelle Locale
# Bronze : données brutes depuis les APIs
# =============================================================================

import requests
import pandas as pd
from pipeline.config import MAX_OFFSET
from pipeline.db import init_schemas, load_to_bronze

BASE_PARIS   = "https://opendata.paris.fr/api/explore/v2.1/catalog/datasets"
BASE_CULTURE = "https://data.culture.gouv.fr/api/explore/v2.1/catalog/datasets"


def _fetch_all(url: str, params: dict = None, limit: int = 100) -> pd.DataFrame:
    p = {"limit": limit, "offset": 0}
    if params:
        p.update(params)
    records = []
    while True:
        for attempt in range(3):
            try:
                r = requests.get(url, params=p, timeout=90)
                r.raise_for_status()
                break
            except requests.exceptions.Timeout:
                if attempt == 2:
                    raise
                print(f"    timeout, retry {attempt + 1}/3...", end="\r")
        batch = r.json().get("results", [])
        records.extend(batch)
        print(f"    {len(records)} enregistrements...", end="\r")
        if len(batch) < limit or p["offset"] >= MAX_OFFSET:
            break
        p["offset"] += limit
    print()
    return pd.DataFrame(records)


def fetch_que_faire_paris() -> pd.DataFrame:
    """Événements géolocalisés Que Faire à Paris."""
    print("  Appel API Que Faire à Paris...")
    return _fetch_all(f"{BASE_PARIS}/que-faire-a-paris-/records")


def fetch_creneaux_sportifs() -> pd.DataFrame:
    """Taux de remplissage des équipements sportifs municipaux."""
    print("  Appel API Créneaux sportifs...")
    return _fetch_all(f"{BASE_PARIS}/occupation-des-creneaux-sportifs/records")


def fetch_equipements_culturels() -> pd.DataFrame:
    """Lieux et équipements culturels Paris (Basilic — ministère de la Culture)."""
    print("  Appel API Équipements culturels...")
    return _fetch_all(
        f"{BASE_CULTURE}/base-des-lieux-et-des-equipements-culturels/records",
        params={"refine": "departement:Paris"}
    )


def fetch_associations() -> pd.DataFrame:
    """
    Associations à Paris depuis le Répertoire National des Associations (RNA).
    Lit directement le fichier dpt_75 déjà téléchargé, ou télécharge le ZIP si absent.
    """
    import io, zipfile, glob as _glob, os
    from pathlib import Path

    # Chercher le fichier dpt_75 local en priorité
    bronze_dir = Path(__file__).parents[2] / "data" / "bronze"
    local_files = sorted(_glob.glob(str(bronze_dir / "**" / "*_dpt_75.csv"), recursive=True))

    try:
        if local_files:
            print(f"  Lecture locale : {Path(local_files[0]).name}")
            df = pd.read_csv(local_files[0], sep=";", encoding="utf-8-sig", low_memory=False)
        else:
            print("  Téléchargement RNA associations Paris (~100 Mo)...")
            url = "https://media.interieur.gouv.fr/rna/rna_import_20260407.zip"
            headers = {"User-Agent": "Mozilla/5.0 (compatible; urban-data-explorer/1.0)"}
            r = requests.get(url, headers=headers, timeout=180, stream=True)
            r.raise_for_status()
            z = zipfile.ZipFile(io.BytesIO(r.content))
            csv_name = next(n for n in z.namelist() if "_dpt_75" in n)
            with z.open(csv_name) as f:
                df = pd.read_csv(f, sep=";", encoding="utf-8-sig", low_memory=False)

        print(f"    {len(df)} associations Paris")
        return df
    except Exception as e:
        print(f"  [WARN] RNA non disponible ({e}) — source ignorée")
        return pd.DataFrame()


def run():
    init_schemas()

    print("\n[1/4] Que Faire à Paris")
    df = fetch_que_faire_paris()
    load_to_bronze(df, "que_faire_paris")

    print("\n[2/4] Créneaux sportifs")
    df = fetch_creneaux_sportifs()
    load_to_bronze(df, "creneaux_sportifs")

    print("\n[3/4] Équipements culturels")
    df = fetch_equipements_culturels()
    load_to_bronze(df, "equipements_culturels")

    print("\n[4/4] Associations (RNA)")
    df = fetch_associations()
    if not df.empty:
        load_to_bronze(df, "associations_paris")


if __name__ == "__main__":
    run()
