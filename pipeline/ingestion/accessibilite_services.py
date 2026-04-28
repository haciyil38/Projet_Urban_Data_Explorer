"""
INGESTION — AccessScore (V6 - Static Version)
Lecture des fichiers standardises stockes dans le repo (data/static/).
"""

import os
import pandas as pd
from pipeline.db import init_schemas, load_to_bronze

# Chemins locaux vers les fichiers standardises
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STATIC_DATA_DIR = os.path.join(BASE_DIR, "data", "static")

FILES = {
    "commerces": os.path.join(STATIC_DATA_DIR, "commerces_paris.csv"),
    "medecins": os.path.join(STATIC_DATA_DIR, "medecins_paris.csv"),
    "hopitaux": os.path.join(STATIC_DATA_DIR, "hopitaux_paris.csv"),
    "ecoles": os.path.join(STATIC_DATA_DIR, "ecoles_paris.csv")
}

def run():
    init_schemas()
    
    for name, path in FILES.items():
        print(f"Ingestion {name} depuis {path}...")
        if os.path.exists(path):
            df = pd.read_csv(path)
            load_to_bronze(df, f"access_{name}_raw")
        else:
            print(f"  [ERR] Fichier introuvable: {path}")

if __name__ == "__main__":
    run()
