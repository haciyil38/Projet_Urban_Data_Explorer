"""
INGESTION — AccessScore (V2)
Bronze : donnees brutes normalisees par source officielle.

Architecture Bronze:
  bronze.access_commerces_raw  (SIRENE geolocalise)
  bronze.access_medecins_raw   (RPPS / FINESS praticiens)
  bronze.access_hopitaux_raw   (FINESS etablissements)
  bronze.access_ecoles_raw     (Annuaire Education nationale)

Chaque table bronze est stockee au format commun:
  id, nom, lat, lon, code_postal, categorie, type_service, source
"""

import os
import gzip
import zipfile
from io import BytesIO
from pathlib import Path

import pandas as pd
import requests

from pipeline.db import init_schemas, load_to_bronze
from pipeline.geocoding import geocode_dataframe

DATA_DIR = Path(__file__).parents[2] / "data" / "bronze" / "accessscore_sources"

# Paris intra-muros approx
LAT_MIN, LAT_MAX = 48.80, 48.92
LON_MIN, LON_MAX = 2.20, 2.55

# URLs configurables (pour brancher exactement les jeux de donnees choisis)
URL_SIRENE = os.getenv("ACCESS_URL_SIRENE", "")
URL_RPPS = os.getenv("ACCESS_URL_RPPS", "")
URL_FINESS_HOP = os.getenv("ACCESS_URL_FINESS_HOP", "")
URL_ECOLES = os.getenv("ACCESS_URL_ECOLES", "")


def _read_local_or_url(local_name: str, url: str, sep: str | None = None, skiprows: int = 0) -> pd.DataFrame:
    local_path = DATA_DIR / local_name
    if local_path.exists():
        print(f"  Lecture locale: {local_path.name}")
        return pd.read_csv(local_path, sep=sep, skiprows=skiprows, low_memory=False)

    if url:
        print(f"  Telechargement: {url}")
        r = requests.get(url, timeout=300)
        r.raise_for_status()
        content = r.content

        # Certaines ressources .csv/.txt sont servies en gzip.
        if len(content) >= 2 and content[0] == 0x1F and content[1] == 0x8B:
            content = gzip.GzipFile(fileobj=BytesIO(content)).read()

        # Certaines ressources sont publiees en ZIP.
        if url.lower().endswith(".zip"):
            with zipfile.ZipFile(BytesIO(content)) as zf:
                csv_name = next((n for n in zf.namelist() if n.lower().endswith(".csv")), None)
                if csv_name is None:
                    print("  [WARN] ZIP sans CSV exploitable")
                    return pd.DataFrame()
                with zf.open(csv_name) as f:
                    return pd.read_csv(f, sep=sep, skiprows=skiprows, low_memory=False)

        return pd.read_csv(BytesIO(content), sep=sep, skiprows=skiprows, low_memory=False)

    print(f"  [WARN] Source absente (ni fichier local, ni URL): {local_name}")
    return pd.DataFrame()


def _get_first_existing(df: pd.DataFrame, candidates: list[str], default=None):
    for c in candidates:
        if c in df.columns:
            return c
    return default


def _normalize_common(
    df: pd.DataFrame,
    category: str,
    source: str,
    id_candidates: list[str],
    name_candidates: list[str],
    lat_candidates: list[str],
    lon_candidates: list[str],
    cp_candidates: list[str],
    type_candidates: list[str],
) -> pd.DataFrame:
    if df.empty:
        return df

    id_col = _get_first_existing(df, id_candidates, df.columns[0])
    name_col = _get_first_existing(df, name_candidates)
    lat_col = _get_first_existing(df, lat_candidates)
    lon_col = _get_first_existing(df, lon_candidates)
    cp_col = _get_first_existing(df, cp_candidates)
    type_col = _get_first_existing(df, type_candidates)

    if lat_col is None or lon_col is None:
        print("  [WARN] Colonnes latitude/longitude introuvables")
        return pd.DataFrame()

    out = pd.DataFrame()
    out["id"] = df[id_col].astype(str)
    out["nom"] = df[name_col].astype(str) if name_col else None
    out["lat"] = pd.to_numeric(df[lat_col], errors="coerce")
    out["lon"] = pd.to_numeric(df[lon_col], errors="coerce")
    out["code_postal"] = df[cp_col].astype(str) if cp_col else None
    out["categorie"] = category
    out["type_service"] = df[type_col].astype(str) if type_col else category
    out["source"] = source

    out = out.dropna(subset=["lat", "lon"])
    out = out[
        out["lat"].between(LAT_MIN, LAT_MAX) &
        out["lon"].between(LON_MIN, LON_MAX)
    ].copy()
    out = out.drop_duplicates(subset=["id", "lat", "lon"])
    return out


def _convert_xy_to_latlon_if_needed(df: pd.DataFrame) -> pd.DataFrame:
    """
    Convertit des coordonnees X/Y Lambert93 vers latitude/longitude WGS84 si necessaire.
    """
    if "latitude" in df.columns and "longitude" in df.columns:
        return df
    if "lat" in df.columns and "lon" in df.columns:
        return df

    x_col = _get_first_existing(df, ["x", "X", "x_l93", "coordx_origine", "coordxet"])
    y_col = _get_first_existing(df, ["y", "Y", "y_l93", "coordy_origine", "coordyet"])
    if x_col is None or y_col is None:
        return df

    try:
        from pyproj import Transformer
    except Exception:
        print("  [WARN] pyproj indisponible: conversion X/Y non effectuee")
        return df

    x = pd.to_numeric(df[x_col], errors="coerce")
    y = pd.to_numeric(df[y_col], errors="coerce")
    valid = x.notna() & y.notna()
    if not valid.any():
        return df

    transformer = Transformer.from_crs("EPSG:2154", "EPSG:4326", always_xy=True)
    lon, lat = transformer.transform(x[valid].values, y[valid].values)
    df = df.copy()
    df.loc[valid, "latitude"] = lat
    df.loc[valid, "longitude"] = lon
    return df


def _geocode_if_missing_latlon(
    df: pd.DataFrame,
    id_col: str,
    address_col: str,
    cp_col: str | None,
) -> pd.DataFrame:
    lat_col = _get_first_existing(df, ["latitude", "lat"])
    lon_col = _get_first_existing(df, ["longitude", "lon"])
    if lat_col and lon_col:
        return df

    if address_col not in df.columns:
        return df

    to_geo = df[[id_col, address_col] + ([cp_col] if cp_col and cp_col in df.columns else [])].copy()
    to_geo = to_geo.dropna(subset=[address_col])
    if to_geo.empty:
        return df

    geocoded = geocode_dataframe(
        to_geo,
        col_adresse=address_col,
        col_codepostal=cp_col if cp_col and cp_col in to_geo.columns else None,
        id_col=id_col,
    )
    if geocoded.empty:
        return df

    merged = df.merge(geocoded[[id_col, "lat", "lon"]], on=id_col, how="left")
    if "latitude" not in merged.columns:
        merged["latitude"] = merged["lat"]
    if "longitude" not in merged.columns:
        merged["longitude"] = merged["lon"]
    return merged


def fetch_commerces_sirene() -> pd.DataFrame:
    """
    SIRENE geolocalise:
    - priorite au fichier local data/bronze/accessscore_sources/sirene.csv
    - ou URL ACCESS_URL_SIRENE
    """
    print("  Source commerces: SIRENE geolocalise")
    raw = _read_local_or_url("sirene.csv", URL_SIRENE, sep=";")
    if raw.empty:
        return raw

    raw = _convert_xy_to_latlon_if_needed(raw)

    # Filtrage NAF commerce alimentaire (prefixes simples V2)
    naf_col = _get_first_existing(raw, ["activitePrincipaleEtablissement", "naf", "code_naf"])
    if naf_col:
        raw = raw[raw[naf_col].astype(str).str.startswith(("47.11", "47.21", "47.22", "47.29"), na=False)]

    return _normalize_common(
        raw,
        category="commerces",
        source="sirene",
        id_candidates=["siret", "id", "id_etablissement"],
        name_candidates=["enseigne1Etablissement", "denominationUniteLegale", "nom", "raison_sociale"],
        lat_candidates=["latitude", "lat"],
        lon_candidates=["longitude", "lon"],
        cp_candidates=["codePostalEtablissement", "code_postal", "cp"],
        type_candidates=[naf_col] if naf_col else ["naf", "code_naf"],
    )


def fetch_medecins_rpps() -> pd.DataFrame:
    print("  Source medecins: RPPS/FINESS")
    raw = _read_local_or_url("rpps.csv", URL_RPPS, sep="|")
    if raw.empty:
        return raw

    # Restreindre Paris si possible pour reduire le volume.
    dep_col = _get_first_existing(raw, ["Code Département (structure)", "code_departement", "dep"])
    if dep_col:
        raw = raw[raw[dep_col].astype(str).str.strip() == "75"]

    spec_col = _get_first_existing(raw, ["specialite", "profession", "libellé profession", "Libellé profession"])
    if spec_col:
        raw = raw[raw[spec_col].astype(str).str.contains("general", case=False, na=False)]

    # Geocodage de secours RPPS quand lat/lon absents.
    id_col = _get_first_existing(raw, ["Identifiant PP", "id", "id_national", "rpps"], raw.columns[0])
    address_col = _get_first_existing(raw, ["Libellé Voie (coord. structure)", "adresse", "adresse_1"])
    cp_col = _get_first_existing(raw, ["Code postal (coord. structure)", "code_postal", "cp"])
    if address_col:
        num_col = _get_first_existing(raw, ["Numéro Voie (coord. structure)", "numero_voie"], None)
        num_series = raw[num_col].fillna("").astype(str).str.strip() if num_col else ""
        raw[address_col] = (num_series + " " + raw[address_col].fillna("").astype(str).str.strip()).str.strip()
        raw = _geocode_if_missing_latlon(raw, id_col=id_col, address_col=address_col, cp_col=cp_col)

    return _normalize_common(
        raw,
        category="medecins",
        source="rpps",
        id_candidates=["Identifiant PP", "id", "id_national", "rpps"],
        name_candidates=["Nom d'exercice", "nom_exercice", "nom", "raison_sociale"],
        lat_candidates=["latitude", "lat"],
        lon_candidates=["longitude", "lon"],
        cp_candidates=["Code postal (coord. structure)", "code_postal", "cp"],
        type_candidates=[spec_col] if spec_col else ["specialite"],
    )


def fetch_hopitaux_finess() -> pd.DataFrame:
    print("  Source hopitaux: FINESS etablissements")
    # Le flux geolocalise FINESS contient une premiere ligne meta a ignorer.
    raw = _read_local_or_url("finess_hopitaux.csv", URL_FINESS_HOP, sep=";", skiprows=1)
    if raw.empty:
        return raw

    raw = _convert_xy_to_latlon_if_needed(raw)

    cat_col = _get_first_existing(raw, ["categorie_etablissement", "type_etablissement", "categorie", "categagretab"])
    if cat_col:
        raw = raw[raw[cat_col].astype(str).str.contains("hopital|clinique|urgence", case=False, na=False)]

    # Geocodage de secours si pas de lat/lon.
    id_col = _get_first_existing(raw, ["nofinesset", "finess", "id"], raw.columns[0])
    address_col = _get_first_existing(raw, ["ligneacheminement", "adresse", "adresse_1"])
    cp_col = _get_first_existing(raw, ["codepostal", "code_postal", "cp"])
    if address_col:
        raw = _geocode_if_missing_latlon(raw, id_col=id_col, address_col=address_col, cp_col=cp_col)

    return _normalize_common(
        raw,
        category="hopitaux",
        source="finess",
        id_candidates=["finess", "nofinesset", "id"],
        name_candidates=["rs", "raison_sociale", "nom"],
        lat_candidates=["latitude", "lat"],
        lon_candidates=["longitude", "lon"],
        cp_candidates=["codepostal", "code_postal", "cp"],
        type_candidates=[cat_col] if cat_col else ["categorie"],
    )


def fetch_ecoles_education_nat() -> pd.DataFrame:
    print("  Source ecoles: Annuaire Education nationale")
    raw = _read_local_or_url("ecoles.csv", URL_ECOLES, sep=";")
    if raw.empty:
        return raw

    niv_col = _get_first_existing(raw, ["Type_etablissement", "nature_uai_libe", "type_etablissement", "niveau"])
    if niv_col:
        raw = raw[raw[niv_col].astype(str).str.contains("maternelle|elementaire|primaire|ecole", case=False, na=False)]

    return _normalize_common(
        raw,
        category="ecoles",
        source="education_nationale",
        id_candidates=["Identifiant_de_l_etablissement", "identifiant_de_l_etablissement", "uai", "id"],
        name_candidates=["Nom_etablissement", "nom_etablissement", "appellation_officielle", "nom"],
        lat_candidates=["latitude", "lat"],
        lon_candidates=["longitude", "lon"],
        cp_candidates=["Code_postal", "code_postal", "codepostal", "cp"],
        type_candidates=[niv_col] if niv_col else ["niveau"],
    )


def run():
    init_schemas()

    print("\n[1/4] Commerces (SIRENE)")
    load_to_bronze(fetch_commerces_sirene(), "access_commerces_raw")

    print("\n[2/4] Medecins (RPPS)")
    load_to_bronze(fetch_medecins_rpps(), "access_medecins_raw")

    print("\n[3/4] Hopitaux (FINESS)")
    load_to_bronze(fetch_hopitaux_finess(), "access_hopitaux_raw")

    print("\n[4/4] Ecoles (Education nationale)")
    load_to_bronze(fetch_ecoles_education_nat(), "access_ecoles_raw")


if __name__ == "__main__":
    run()
