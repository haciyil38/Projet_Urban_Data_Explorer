# =============================================================================
# DB — Connexion PostgreSQL + helpers Bronze / Silver / Gold
# =============================================================================

import json
import pandas as pd
from sqlalchemy import create_engine, text
from pymongo import MongoClient
from pipeline.config import DB_URL, MONGO_URL


_engine = None

def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(
            DB_URL,
            pool_size=5,
            max_overflow=5,
            pool_pre_ping=True,
        )
    return _engine


_mongo_client = None

def get_mongo_client():
    global _mongo_client
    if _mongo_client is None:
        _mongo_client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=5000)
    return _mongo_client


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


def load_to_mongo_bronze(df: pd.DataFrame, collection_name: str, if_exists: str = "replace"):
    """
    Charge un DataFrame dans la base MongoDB (Data Lake Bronze).
    if_exists : 'replace' (écrase la collection) ou 'append' (ajoute des documents)
    """
    if df.empty:
        print(f"  [SKIP] {collection_name} — DataFrame vide")
        return
    
    client = get_mongo_client()
    db = client["paris_datalake"]
    collection = db[collection_name]
    
    if if_exists == "replace":
        collection.drop()
        
    # Convertit le DataFrame en liste de dictionnaires. Les NaN deviennent None.
    records = df.where(pd.notnull(df), None).to_dict(orient="records")
    if records:
        collection.insert_many(records)
    print(f"  → mongodb.paris_datalake.{collection_name} : {len(records)} documents chargés")


def read_bronze(table_name: str) -> pd.DataFrame:
    """Lit une table du schéma bronze (PostgreSQL)."""
    return pd.read_sql(f"SELECT * FROM bronze.{table_name}", get_engine())

def read_mongo_bronze(collection_name: str) -> pd.DataFrame:
    """Lit une collection de la base MongoDB (Data Lake Bronze) et la renvoie en DataFrame Pandas."""
    client = get_mongo_client()
    db = client["paris_datalake"]
    collection = db[collection_name]
    
    # On récupère tous les documents (sans l'ID MongoDB `_id` pour que ça ressemble au SQL)
    cursor = collection.find({}, {"_id": 0})
    df = pd.DataFrame(list(cursor))
    return df


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


# --- Helpers Gold MongoDB ---

def load_to_mongo_gold(df: pd.DataFrame, collection_name: str, if_exists: str = "replace"):
    """Charge un DataFrame dans MongoDB (Gold — indicateurs finaux)."""
    if df.empty:
        print(f"  [SKIP] {collection_name} — DataFrame vide")
        return
    client = get_mongo_client()
    db = client["paris_gold"]
    collection = db[collection_name]
    if if_exists == "replace":
        collection.drop()
    records = df.where(pd.notnull(df), None).to_dict(orient="records")
    if records:
        collection.insert_many(records)
    print(f"  → mongodb.paris_gold.{collection_name} : {len(records)} documents chargés")


def read_mongo_gold(collection_name: str) -> pd.DataFrame:
    """Lit une collection MongoDB Gold et la retourne en DataFrame."""
    client = get_mongo_client()
    db = client["paris_gold"]
    cursor = db[collection_name].find({}, {"_id": 0})
    return pd.DataFrame(list(cursor))
