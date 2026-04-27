# =============================================================================
# TRANSFORMATION — Indicateur Vélib / Mobilité douce
# Silver : table silver.velib_stations avec géométrie PostGIS
#
# Source bronze :
#   - velib_station_information  : station_id, stationCode, name, lat, lon, capacity
#   - velib_station_status       : station_id, stationCode, num_bikes_available,
#                                  num_docks_available, num_bikes_available_types,
#                                  is_installed, is_renting
# =============================================================================

import json
import pandas as pd
from sqlalchemy import text

from pipeline.db import get_engine, read_bronze


def _init_silver_table():
    """Crée la table silver.velib_stations avec index GIST."""
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS silver.velib_stations (
                station_id          TEXT PRIMARY KEY,
                nom                 TEXT,
                capacite            INTEGER,
                num_velos_dispo     INTEGER,
                num_velos_meca      INTEGER,
                num_velos_elec      INTEGER,
                num_bornes_dispo    INTEGER,
                taux_disponibilite  DOUBLE PRECISION,
                is_installed        BOOLEAN,
                is_renting          BOOLEAN,
                lat                 DOUBLE PRECISION,
                lon                 DOUBLE PRECISION,
                geom                GEOMETRY(Point, 4326),
                updated_at          TIMESTAMP DEFAULT NOW()
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_velib_geom
            ON silver.velib_stations USING GIST(geom)
        """))
        conn.commit()
    print("  Table silver.velib_stations prête.")


def _oui_non_to_bool(series: pd.Series) -> pd.Series:
    """Convertit 'OUI'/'NON' et 1/0 en booléen."""
    def _conv(v):
        if isinstance(v, bool):
            return v
        if isinstance(v, (int, float)):
            return bool(v)
        if isinstance(v, str):
            return v.strip().upper() in ("OUI", "TRUE", "1", "YES")
        return True
    return series.apply(_conv)


def _extract_coords(df: pd.DataFrame) -> pd.DataFrame:
    """Extrait lat/lon depuis la colonne coordonnees_geo si nécessaire."""
    if "coordonnees_geo" not in df.columns or ("lat" in df.columns and "lon" in df.columns):
        return df

    def _parse(v):
        if isinstance(v, dict):
            return v.get("lat"), v.get("lon")
        if isinstance(v, str):
            try:
                d = json.loads(v)
                return d.get("lat"), d.get("lon")
            except Exception:
                pass
        return None, None

    coords = df["coordonnees_geo"].apply(_parse)
    df = df.copy()
    df["lat"] = [c[0] for c in coords]
    df["lon"] = [c[1] for c in coords]
    return df


def _parse_available_types(value) -> tuple[int, int]:
    """Extrait (mechanical, ebike) depuis num_bikes_available_types."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except Exception:
            value = []
    if not isinstance(value, list):
        return 0, 0

    mechanical = 0
    ebike = 0
    for item in value:
        if not isinstance(item, dict):
            continue
        mechanical += int(item.get("mechanical", 0) or 0)
        ebike += int(item.get("ebike", 0) or 0)
    return mechanical, ebike


def _get_col_series(df: pd.DataFrame, col: str) -> pd.Series:
    """Retourne une Series même si le label de colonne est dupliqué."""
    value = df[col]
    if isinstance(value, pd.DataFrame):
        return value.iloc[:, 0]
    return value


def build_silver_stations() -> int:
    """Joint info + status, construit la table silver.velib_stations."""
    engine = get_engine()

    # ── Lecture bronze ─────────────────────────────────────────────────────
    info_df   = read_bronze("velib_station_information")
    status_df = read_bronze("velib_station_status")

    # ── Normalisation clé commune ──────────────────────────────────────────
    # Les flux GBFS exposent station_id et/ou stationCode selon les usages.
    # On normalise vers une seule clé : station_id.
    for df in (info_df, status_df):
        if "station_id" in df.columns:
            continue
        for alt in ("stationCode", "stationcode", "stationid", "id"):
            if alt in df.columns:
                df.rename(columns={alt: "station_id"}, inplace=True)
                break

    # ── Extraction coordonnées ─────────────────────────────────────────────
    info_df = _extract_coords(info_df)

    # ── Sélection colonnes info ────────────────────────────────────────────
    rename_info = {"name": "nom", "capacity": "capacite"}
    info_df = info_df.rename(columns={k: v for k, v in rename_info.items() if k in info_df.columns})
    info_df = info_df.loc[:, ~info_df.columns.duplicated()]
    keep = [c for c in ["station_id", "nom", "capacite", "lat", "lon"] if c in info_df.columns]
    info_df = info_df[keep].drop_duplicates(subset=["station_id"])

    # ── Sélection colonnes status ──────────────────────────────────────────
    rename_status = {
        "num_bikes_available":  "num_velos_dispo",
        "numBikesAvailable":    "num_velos_dispo",
        "num_docks_available":  "num_bornes_dispo",
        "numDocksAvailable":    "num_bornes_dispo",
        "is_installed":         "is_installed",
        "is_renting":           "is_renting",
    }
    status_df = status_df.rename(columns={k: v for k, v in rename_status.items() if k in status_df.columns})
    status_df = status_df.loc[:, ~status_df.columns.duplicated()]

    if "num_bikes_available_types" in status_df.columns:
        parsed = status_df["num_bikes_available_types"].apply(_parse_available_types)
        status_df["num_velos_meca"] = [v[0] for v in parsed]
        status_df["num_velos_elec"] = [v[1] for v in parsed]

    keep_s = [c for c in ["station_id", "num_velos_dispo", "num_bornes_dispo",
                           "num_velos_meca", "num_velos_elec", "is_installed", "is_renting",
                           # certaines API mettent capacity/name ici aussi
                           "nom", "capacite", "lat", "lon"]
              if c in status_df.columns]
    status_df = status_df[keep_s].drop_duplicates(subset=["station_id"])

    # ── Merge ──────────────────────────────────────────────────────────────
    merged = info_df.merge(status_df, on="station_id", how="inner", suffixes=("", "_s"))
    merged = merged.loc[:, ~merged.columns.duplicated()]

    # Fusionner colonnes dupliquées (préférer info_ pour nom/capacite/coords)
    for col in ["nom", "capacite", "lat", "lon"]:
        dup = f"{col}_s"
        if dup in merged.columns:
            merged[col] = _get_col_series(merged, col).combine_first(_get_col_series(merged, dup))
            merged.drop(columns=[dup], inplace=True)

    print(f"  {len(merged)} stations après jointure")

    # ── Valeurs manquantes ─────────────────────────────────────────────────
    for col, default in [("num_velos_dispo", 0), ("num_bornes_dispo", 0),
                          ("num_velos_meca",  0), ("num_velos_elec",   0)]:
        if col not in merged.columns:
            merged[col] = default

    for col in ["num_velos_dispo", "num_bornes_dispo", "num_velos_meca", "num_velos_elec", "capacite"]:
        merged[col] = pd.to_numeric(_get_col_series(merged, col), errors="coerce").fillna(0).astype(int)

    # Booléens is_installed / is_renting
    for col in ("is_installed", "is_renting"):
        if col in merged.columns:
            merged[col] = _oui_non_to_bool(_get_col_series(merged, col))
        else:
            merged[col] = True

    # ── Taux de disponibilité ──────────────────────────────────────────────
    merged["taux_disponibilite"] = merged.apply(
        lambda r: r["num_velos_dispo"] / r["capacite"] if r["capacite"] > 0 else 0.0,
        axis=1,
    )

    # ── Filtrage géographique ──────────────────────────────────────────────
    # Vélib couvre la métropole parisienne (pas seulement intra-muros)
    merged = merged.dropna(subset=["lat", "lon"])
    merged["lat"] = pd.to_numeric(_get_col_series(merged, "lat"), errors="coerce")
    merged["lon"] = pd.to_numeric(_get_col_series(merged, "lon"), errors="coerce")
    merged = merged.dropna(subset=["lat", "lon"])
    merged = merged[merged["lat"].between(48.70, 49.00) & merged["lon"].between(2.10, 2.65)]
    print(f"  {len(merged)} stations dans la métropole avec coordonnées")

    # ── Insertion bulk ─────────────────────────────────────────────────────
    rows = [
        {
            "sid":    str(row["station_id"]),
            "nom":    str(row.get("nom", "")),
            "cap":    int(row["capacite"]),
            "velos":  int(row["num_velos_dispo"]),
            "meca":   int(row.get("num_velos_meca", 0)),
            "elec":   int(row.get("num_velos_elec", 0)),
            "bornes": int(row.get("num_bornes_dispo", 0)),
            "taux":   float(row["taux_disponibilite"]),
            "inst":   bool(row["is_installed"]),
            "rent":   bool(row["is_renting"]),
            "lat":    float(row["lat"]),
            "lon":    float(row["lon"]),
        }
        for _, row in merged.iterrows()
    ]

    with engine.connect() as conn:
        conn.execute(text("TRUNCATE silver.velib_stations"))
        if rows:
            conn.execute(
                text("""
                    INSERT INTO silver.velib_stations
                        (station_id, nom, capacite, num_velos_dispo, num_velos_meca, num_velos_elec,
                         num_bornes_dispo, taux_disponibilite, is_installed, is_renting, lat, lon, geom)
                    VALUES
                        (:sid, :nom, :cap, :velos, :meca, :elec, :bornes, :taux, :inst, :rent,
                         :lat, :lon, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326))
                """),
                rows,
            )
        conn.commit()

    print(f"  → {len(rows)} stations chargées dans silver.velib_stations")
    return len(rows)


def run():
    print("=== TRANSFORMATION VÉLIB ===")
    _init_silver_table()
    build_silver_stations()
    print("=== TRANSFORMATION VÉLIB TERMINÉE ===")


if __name__ == "__main__":
    run()
