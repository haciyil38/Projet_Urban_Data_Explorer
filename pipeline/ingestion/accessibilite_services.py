"""
INGESTION — AccessScore (V4 - Ultra-Stable)
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

# URLs stables et vérifiées
URLS = {
    "commerces": "https://object.files.data.gouv.fr/data-pipeline-open/siren/stock/StockEtablissement_utf8.zip",
    "medecins": "https://static.data.gouv.fr/resources/annuaire-sante-extractions-des-donnees-en-libre-acces-des-professionnels-intervenant-dans-le-systeme-de-sante-rpps/20260427-075032/ps-libreacces-personne-activite.txt",
    "hopitaux": "https://static.data.gouv.fr/resources/finess-extraction-du-fichier-des-etablissements/20260312-094547/etalab-cs1100507-stock-20260311-0343.csv",
    "ecoles": "https://static.data.gouv.fr/resources/annuaire-de-leducation/20190912-161323/fr-en-annuaire-education.csv"
}

def filter_paris_flexible(df):
    """Filtre un DataFrame pour Paris (75) en cherchant intelligemment la colonne departement."""
    if df.empty: return df
    # Liste de noms de colonnes probables
    possible_cols = ['code_departement', 'dep', 'code_dept', 'département', 'cp', 'codepostal']
    
    # Recherche exacte puis partielle
    target_col = None
    for col in df.columns:
        if col.lower() in possible_cols:
            target_col = col
            break
    
    if not target_col:
        for col in df.columns:
            if any(p in col.lower() for p in ['dept', 'dep', 'postal']):
                target_col = col
                break
                
    if target_col:
        print(f"    Filtrage via colonne: {target_col}")
        return df[df[target_col].astype(str).str.startswith("75")].copy()
    
    print("    [WARN] Aucune colonne de departement identifiee, retour des 1000 premieres lignes.")
    return df.head(1000).copy()

def fetch_source(name, url, sep=';', encoding='latin1', compression=None):
    print(f"  Source {name}: {url}")
    try:
        if compression == 'zip':
            r = requests.get(url, stream=True, timeout=30)
            z = zipfile.ZipFile(io.BytesIO(r.content))
            with z.open(z.namelist()[0]) as f:
                # Echantillon pour les gros fichiers
                df = pd.read_csv(f, sep=',', low_memory=False, nrows=1000000)
        else:
            df = pd.read_csv(url, sep=sep, encoding=encoding, low_memory=False)
        
        df_paris = filter_paris_flexible(df)
        return df_paris
    except Exception as e:
        print(f"  [ERR] {name}: {e}")
        return pd.DataFrame()

def run():
    init_schemas()
    
    # 1. Commerces
    print("[1/4] Commerces (SIRENE)")
    df_com = fetch_source("commerces", URLS["commerces"], compression='zip')
    if not df_com.empty: load_to_bronze(df_com, "access_commerces_raw")
    
    # 2. Medecins
    print("[2/4] Medecins (RPPS)")
    # Tentative avec séparateur pipe | pour le RPPS
    df_med = fetch_source("medecins", URLS["medecins"], sep='|')
    if not df_med.empty: load_to_bronze(df_med, "access_medecins_raw")
    
    # 3. Hopitaux
    print("[3/4] Hopitaux (FINESS)")
    df_hop = fetch_source("hopitaux", URLS["hopitaux"])
    if not df_hop.empty: load_to_bronze(df_hop, "access_hopitaux_raw")
    
    # 4. Ecoles
    print("[4/4] Ecoles")
    df_eco = fetch_source("ecoles", URLS["ecoles"])
    if not df_eco.empty: load_to_bronze(df_eco, "access_ecoles_raw")

if __name__ == "__main__":
    run()
