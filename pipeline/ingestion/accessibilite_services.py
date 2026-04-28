"""
INGESTION — AccessScore (V7 - GitHub Hosted Version)
Utilise les donnees standardisees hebergees sur le GitHub de l'utilisateur.
"""

import pandas as pd
import requests
import io
from pipeline.db import init_schemas, load_to_bronze

# URLs RAW de votre propre fork GitHub (DZjeff05)
# Ces fichiers sont garantis stables en format et en contenu.
GITHUB_RAW_BASE = "https://raw.githubusercontent.com/DZjeff05/Projet_Urban_Data_Explorer/dev-score-access/data/static"

URLS = {
    "commerces": f"{GITHUB_RAW_BASE}/commerces_paris.csv",
    "medecins": f"{GITHUB_RAW_BASE}/medecins_paris.csv",
    "hopitaux": f"{GITHUB_RAW_BASE}/hopitaux_paris.csv",
    "ecoles": f"{GITHUB_RAW_BASE}/ecoles_paris.csv"
}

def run():
    init_schemas()
    
    for name, url in URLS.items():
        print(f"Ingestion {name} depuis GitHub...")
        try:
            r = requests.get(url, timeout=20)
            if r.status_code == 200:
                df = pd.read_csv(io.BytesIO(r.content))
                load_to_bronze(df, f"access_{name}_raw")
                print(f"  ✓ {len(df)} lignes chargees.")
            else:
                print(f"  [ERR] Impossible d'acceder au fichier sur GitHub (HTTP {r.status_code})")
        except Exception as e:
            print(f"  [ERR] {name}: {e}")

if __name__ == "__main__":
    run()
