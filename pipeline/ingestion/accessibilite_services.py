"""
INGESTION — AccessScore (V3 - Stable)
Bronze : donnees brutes normalisees par source officielle.
"""

import os
import pandas as pd
import requests
import io
import zipfile
from sqlalchemy import create_engine, text
from pipeline.db import init_schemas, load_to_bronze
from pipeline.config import DB_URL

# URLs stables et vérifiées (avril 2026)
URLS = {
    "commerces": "https://object.files.data.gouv.fr/data-pipeline-open/siren/stock/StockEtablissement_utf8.zip",
    "medecins": "https://static.data.gouv.fr/resources/annuaire-sante-extractions-des-donnees-en-libre-acces-des-professionnels-intervenant-dans-le-systeme-de-sante-rpps/20260427-075032/ps-libreacces-personne-activite.txt",
    "hopitaux": "https://static.data.gouv.fr/resources/finess-extraction-du-fichier-des-etablissements/20260312-094547/etalab-cs1100507-stock-20260311-0343.csv",
    "ecoles": "https://static.data.gouv.fr/resources/annuaire-de-leducation/20190912-161323/fr-en-annuaire-education.csv"
}

def fetch_medecins_rpps():
    print("  Source medecins: RPPS")
    try:
        # On essaie d'abord l'URL directe, sinon on passe
        r = requests.get(URLS["medecins"], stream=True, timeout=10)
        if r.status_code != 200:
             print(f"  [SKIP] RPPS indisponible (HTTP {r.status_code})")
             return pd.DataFrame()
             
        reader = pd.read_csv(io.BytesIO(r.content), sep='|', low_memory=False, chunksize=50000, encoding='latin1')
        chunks = []
        for chunk in reader:
            # On cherche la colonne de département de manière flexible
            dep_col = [c for c in chunk.columns if 'département' in c.lower() or 'code_dept' in c.lower()]
            if dep_col:
                mask = chunk[dep_col[0]].astype(str).str.startswith("75")
                chunks.append(chunk[mask])
        return pd.concat(chunks) if chunks else pd.DataFrame()
    except Exception as e:
        print(f"  [ERR] RPPS: {e}")
        return pd.DataFrame()

def fetch_hopitaux_finess():
    print("  Source hopitaux: FINESS")
    try:
        df = pd.read_csv(URLS["hopitaux"], sep=';', encoding='latin1', low_memory=False)
        # Détection flexible de la colonne département
        dep_col = 'dep' if 'dep' in df.columns else ([c for c in df.columns if 'dep' in c.lower()] + [None])[0]
        if dep_col:
            return df[df[dep_col].astype(str).str.startswith("75")]
        return df
    except Exception as e:
        print(f"  [ERR] FINESS: {e}")
        return pd.DataFrame()

def fetch_ecoles_education_nat():
    print("  Source ecoles: Education Nationale")
    try:
        # Utilisation forcée de latin1 pour éviter UnicodeDecodeError sur Windows
        df = pd.read_csv(URLS["ecoles"], sep=';', low_memory=False, encoding='latin1')
        return df[df["code_departement"].astype(str).str.startswith("75")]
    except Exception as e:
        print(f"  [ERR] ECOLES: {e}")
        return pd.DataFrame()

def fetch_commerces_sirene():
    print("  Source commerces: SIRENE (Echantillon Paris)")
    try:
        r = requests.get(URLS["commerces"], stream=True)
        z = zipfile.ZipFile(io.BytesIO(r.content))
        with z.open(z.namelist()[0]) as f:
            reader = pd.read_csv(f, sep=',', low_memory=False, chunksize=100000, nrows=1000000)
            chunks = []
            for chunk in reader:
                mask = chunk["codePostalEtablissement"].astype(str).str.startswith("75")
                chunks.append(chunk[mask])
            return pd.concat(chunks)
    except Exception as e:
        print(f"  [SKIP] SIRENE: {e}")
        return pd.DataFrame()

def run():
    init_schemas()
    
    print("[1/4] Commerces (SIRENE)")
    df_com = fetch_commerces_sirene()
    if not df_com.empty: 
        load_to_bronze(df_com, "access_commerces_raw")
    
    print("[2/4] Medecins (RPPS)")
    df_med = fetch_medecins_rpps()
    if not df_med.empty: 
        load_to_bronze(df_med, "access_medecins_raw")
    
    print("[3/4] Hopitaux (FINESS)")
    df_hop = fetch_hopitaux_finess()
    if not df_hop.empty: 
        load_to_bronze(df_hop, "access_hopitaux_raw")
    
    print("[4/4] Ecoles")
    df_eco = fetch_ecoles_education_nat()
    if not df_eco.empty: 
        load_to_bronze(df_eco, "access_ecoles_raw")

if __name__ == "__main__":
    run()
