# =============================================================================
# INGESTION — Indicateur Vélib / Mobilité douce
# Bronze : données temps réel officielles Vélib (GBFS Smovengo)
# =============================================================================

import requests
import pandas as pd
from pipeline.db import init_schemas, load_to_bronze

GBFS_BASE = "https://velib-metropole-opendata.smovengo.cloud/opendata/Velib_Metropole"


def _fetch_gbfs(url: str, data_key: str) -> pd.DataFrame:
    for attempt in range(3):
        try:
            r = requests.get(url, timeout=60)
            r.raise_for_status()
            payload = r.json()
            break
        except requests.exceptions.Timeout:
            if attempt == 2:
                raise
            print(f"    timeout, retry {attempt + 1}/3...", end="\r")

    data = payload.get("data", {})
    records = data.get(data_key, [])
    print(f"    {len(records)} stations récupérées")
    return pd.DataFrame(records)


def fetch_station_information() -> pd.DataFrame:
    """Informations statiques des stations Vélib (nom, capacité, coordonnées)."""
    print("  Appel flux GBFS Vélib station_information...")
    return _fetch_gbfs(f"{GBFS_BASE}/station_information.json", "stations")


def fetch_station_status() -> pd.DataFrame:
    """État temps réel des stations Vélib (vélos dispo, bornes libres)."""
    print("  Appel flux GBFS Vélib station_status...")
    return _fetch_gbfs(f"{GBFS_BASE}/station_status.json", "stations")


def run():
    print("=== INGESTION VÉLIB ===")
    init_schemas()

    info_df = fetch_station_information()
    print(f"  → {len(info_df)} stations (informations)")
    load_to_bronze(info_df, "velib_station_information")

    status_df = fetch_station_status()
    print(f"  → {len(status_df)} stations (statut temps réel)")
    load_to_bronze(status_df, "velib_station_status")

    print("=== INGESTION VÉLIB TERMINÉE ===")


if __name__ == "__main__":
    run()
