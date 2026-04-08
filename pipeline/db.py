# =============================================================================
# DB — Connexion PostgreSQL + helpers Bronze / Silver / Gold
# =============================================================================

import json
import pandas as pd
from sqlalchemy import create_engine, text
from pipeline.config import DB_URL


def get_engine():
    return create_engine(DB_URL)


def init_schemas():
    """Crée les schémas bronze / silver / gold s'ils n'existent pas."""
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS bronze"))
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS silver"))
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS gold"))
        conn.commit()
    print("Schémas bronze / silver / gold prêts.")


# --- Helpers Bronze ---

def _serialize_complex_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Convertit les colonnes dict/list en JSON string (PostgreSQL ne les accepte pas nativement)."""
    df = df.copy()
    for col in df.columns:
        if df[col].dtype == object:
            first_valid = df[col].dropna().iloc[0] if not df[col].dropna().empty else None
            if isinstance(first_valid, (dict, list)):
                df[col] = df[col].apply(
                    lambda x: json.dumps(x, ensure_ascii=False) if isinstance(x, (dict, list)) else x
                )
    return df


def load_to_bronze(df: pd.DataFrame, table_name: str, if_exists: str = "replace"):
    """
    Charge un DataFrame dans le schéma bronze.
    if_exists : 'replace' (écrase) ou 'append' (ajoute des lignes — ex: historique Vélib)
    """
    if df.empty:
        print(f"  [SKIP] {table_name} — DataFrame vide")
        return
    df = _serialize_complex_columns(df)
    engine = get_engine()
    df.to_sql(
        name=table_name,
        con=engine,
        schema="bronze",
        if_exists=if_exists,
        index=False,
        chunksize=1000,
        method="multi",
    )
    print(f"  → bronze.{table_name} : {len(df)} lignes chargées")


def read_bronze(table_name: str) -> pd.DataFrame:
    """Lit une table du schéma bronze."""
    return pd.read_sql(f"SELECT * FROM bronze.{table_name}", get_engine())


# --- Helpers Silver ---

def load_to_silver(df: pd.DataFrame, table_name: str, if_exists: str = "replace"):
    """Charge un DataFrame dans le schéma silver."""
    if df.empty:
        print(f"  [SKIP] {table_name} — DataFrame vide")
        return
    df = _serialize_complex_columns(df)
    engine = get_engine()
    df.to_sql(
        name=table_name,
        con=engine,
        schema="silver",
        if_exists=if_exists,
        index=False,
        chunksize=1000,
        method="multi",
    )
    print(f"  → silver.{table_name} : {len(df)} lignes chargées")


def read_silver(table_name: str) -> pd.DataFrame:
    """Lit une table du schéma silver."""
    return pd.read_sql(f"SELECT * FROM silver.{table_name}", get_engine())


# --- Helpers Gold ---

def load_to_gold(df: pd.DataFrame, table_name: str, if_exists: str = "replace"):
    """
    Charge un DataFrame dans le schéma gold.
    Format attendu :
      - arrondissement  TEXT
      - score           FLOAT  (0–100)
      - details         TEXT   (JSON stringifié)
      - computed_at     TIMESTAMP
    """
    if df.empty:
        print(f"  [SKIP] {table_name} — DataFrame vide")
        return
    df = _serialize_complex_columns(df)
    engine = get_engine()
    df.to_sql(
        name=table_name,
        con=engine,
        schema="gold",
        if_exists=if_exists,
        index=False,
        chunksize=1000,
        method="multi",
    )
    print(f"  → gold.{table_name} : {len(df)} lignes chargées")


def read_gold(table_name: str) -> pd.DataFrame:
    """Lit une table du schéma gold."""
    return pd.read_sql(f"SELECT * FROM gold.{table_name}", get_engine())
