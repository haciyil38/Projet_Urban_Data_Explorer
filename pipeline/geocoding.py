# =============================================================================
# GEOCODING — API Adresse du gouvernement français
# https://adresse.data.gouv.fr/api-doc/adresse
#
# Endpoint batch CSV : POST https://api-adresse.data.gouv.fr/search/csv/
#   - Gratuit, sans clé API
#   - Accepte jusqu'à ~50 000 adresses par requête (limite 8 Mo)
#   - Renvoie le CSV enrichi avec result_latitude, result_longitude, result_score
# =============================================================================

import io
import math
import time

import pandas as pd
import requests

_BATCH_URL  = "https://api-adresse.data.gouv.fr/search/csv/"
_CHUNK_SIZE = 2_000   # réduit pour limiter la taille des réponses chunked
_SCORE_MIN  = 0.4     # seuil de confiance du géocodage (0–1)
_MAX_RETRY  = 3       # tentatives par chunk en cas d'erreur réseau


def geocode_dataframe(
    df: pd.DataFrame,
    col_adresse: str,
    col_codepostal: str | None = None,
    id_col: str | None = None,
) -> pd.DataFrame:
    """
    Géocode un DataFrame via l'API Adresse (batch CSV).

    Args:
        df:             DataFrame source (une ligne = une adresse à géocoder)
        col_adresse:    Nom de la colonne contenant la rue / adresse complète
        col_codepostal: Nom de la colonne code postal (optionnel mais améliore la précision)
        id_col:         Colonne identifiant à conserver pour la jointure (optionnel)

    Returns:
        DataFrame avec colonnes ajoutées : lat, lon, geocode_score
        Les lignes non géocodées (score < seuil ou erreur) sont exclues.
    """
    keep = [col for col in [id_col, col_adresse, col_codepostal] if col]
    batch = df[keep].drop_duplicates(subset=[col_adresse, col_codepostal] if col_codepostal else [col_adresse]).copy()
    batch = batch.dropna(subset=[col_adresse])
    batch[col_adresse] = batch[col_adresse].astype(str).str.strip()
    if col_codepostal:
        batch[col_codepostal] = batch[col_codepostal].astype(str).str.strip()

    n_chunks = math.ceil(len(batch) / _CHUNK_SIZE)
    results = []

    for i in range(n_chunks):
        chunk = batch.iloc[i * _CHUNK_SIZE : (i + 1) * _CHUNK_SIZE]
        print(f"    Géocodage chunk {i + 1}/{n_chunks} ({len(chunk)} adresses)...", end="\r")

        # Prépare le CSV en mémoire
        csv_buf = io.StringIO()
        chunk.to_csv(csv_buf, index=False)
        csv_bytes = csv_buf.getvalue().encode("utf-8")

        # Paramètres de l'API
        params = {"columns": col_adresse}
        if col_codepostal:
            params["postcode"] = col_codepostal

        for attempt in range(_MAX_RETRY):
            try:
                r = requests.post(
                    _BATCH_URL,
                    files={"data": ("adresses.csv", csv_bytes, "text/csv")},
                    data=params,
                    timeout=120,
                )
                r.raise_for_status()
                break
            except (requests.exceptions.ChunkedEncodingError,
                    requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout) as e:
                if attempt == _MAX_RETRY - 1:
                    raise
                print(f"\n    [retry {attempt + 1}/{_MAX_RETRY - 1}] Erreur réseau : {e}")
                time.sleep(5)

        chunk_result = pd.read_csv(io.StringIO(r.text))
        results.append(chunk_result)

    print()
    if not results:
        return pd.DataFrame()

    out = pd.concat(results, ignore_index=True)

    # Filtrer sur le score de confiance et les coordonnées valides
    out = out.rename(columns={
        "latitude":     "lat",
        "longitude":    "lon",
        "result_score": "geocode_score",
    })
    out = out[out["geocode_score"] >= _SCORE_MIN]
    out["lat"] = pd.to_numeric(out["lat"], errors="coerce")
    out["lon"] = pd.to_numeric(out["lon"], errors="coerce")
    out = out.dropna(subset=["lat", "lon"])

    print(f"    → {len(out)} adresses géocodées avec score ≥ {_SCORE_MIN}")
    return out
