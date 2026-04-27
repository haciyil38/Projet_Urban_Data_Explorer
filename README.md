# Urban Data Explorer — Paris

Dashboard interactif d'indicateurs urbains parisiens, construit sur une architecture Bronze / Silver / Gold.

---

## Prérequis

- **Docker Desktop** (pour PostgreSQL/PostGIS)
- **Python 3.11+** avec un virtualenv `.venv`
- **Git**

---

## Installation

### 1. Cloner le dépôt

```bash
git clone https://github.com/haciyil38/Projet_Urban_Data_Explorer
cd "Projet Data Archi"
```

### 2. Créer le virtualenv et installer les dépendances

```bash
python3 -m venv .venv
source .venv/bin/activate      # macOS / Linux
# .venv\Scripts\activate       # Windows
pip install -r requirements.txt
```

### 3. Configurer l'environnement

```bash
cp .env.example .env
```

Le fichier `.env` par défaut fonctionne tel quel avec Docker. Ne le modifier que si vous avez une base PostgreSQL externe.

### 4. Données requises (non versionnées)

Certains fichiers volumineux doivent être placés manuellement dans `data/` :

| Fichier | Chemin attendu | Source |
|---|---|---|
| Populations légales INSEE | `data/referentiel/ensemble/donnees_communes.csv` | [insee.fr — Populations légales 2021](https://www.insee.fr/fr/statistiques/2011101) → ZIP "Communes" |
| RNA Associations (dpt 75) | `data/bronze/rna_import_<date>/rna_import_<date>_dpt_75.csv` | [data.gouv.fr — RNA](https://www.data.gouv.fr/fr/datasets/repertoire-national-des-associations/) |
| RPLS Logements sociaux *(optionnel)* | `data/bronze/rpls_logements_sociaux.csv` | [data.gouv.fr — RPLS](https://www.data.gouv.fr/fr/datasets/repertoire-des-logements-locatifs-des-bailleurs-sociaux/) — si le téléchargement automatique échoue (~3 Go) |

> Les autres sources (DVF, Filosofi, OpenData Paris, API Adresse…) sont téléchargées automatiquement par le pipeline.

---

## Démarrage

Le script `start.sh` gère tout :

```bash
# Lancer uniquement la base + l'API + le frontend
./start.sh

# Lancer la base ET relancer tout le pipeline de données (long ~10–20 min)
./start.sh --pipeline
```

Accès une fois démarré :

| Service | URL |
|---|---|
| **Dashboard** | http://127.0.0.1:8080/frontend/public/index.html |
| **API (docs Swagger)** | http://127.0.0.1:8000/docs |

Arrêt propre : `Ctrl+C`

---

## Architecture

```
.
├── pipeline/
│   ├── ingestion/          # Bronze  — récupération données brutes
│   ├── transformation/     # Silver  — nettoyage, géocodage, points PostGIS
│   └── indicators/         # Gold    — scores / indicateurs finaux
├── api/
│   ├── main.py             # FastAPI app + CORS
│   └── routes/             # Un fichier par indicateur
├── frontend/
│   ├── public/index.html   # Page principale
│   └── src/
│       ├── map/            # MapLibre GL JS (carte, couches, choroplèthe)
│       └── components/     # CSS
├── data/
│   ├── bronze/             # Données brutes (non versionnées)
│   ├── silver/             # Données nettoyées (non versionnées)
│   ├── gold/               # Indicateurs finaux (non versionnées)
│   └── referentiel/        # GeoJSON arrondissements, populations INSEE
├── docker-compose.yml      # PostgreSQL + PostGIS (port 5433)
├── start.sh                # Script de démarrage
└── requirements.txt
```

### Schémas PostgreSQL

| Schéma | Contenu |
|---|---|
| `bronze` | Données brutes importées (une table par source) |
| `silver` | Données nettoyées avec géométries PostGIS |
| `gold` | Scores et indicateurs agrégés exposés par l'API |

---

## Indicateurs disponibles

### Vitalité Culturelle Locale

Score calculé **à la demande** autour d'un point GPS (lat/lon + rayon en mètres) via PostGIS `ST_DWithin`.

Sources : événements OpenAgenda · équipements culturels (data.culture.gouv.fr) · équipements sportifs (data.gouv.fr) · associations RNA

Endpoint : `GET /indicators/vitalite-culturelle?lat=48.86&lon=2.35&radius_m=500`

### Immobilier

Choroplèthe par arrondissement — prix médian au m², évolution annuelle, revenus médians, logements sociaux.

Sources : DVF (transactions 2020–2024) · RPLS · INSEE Filosofi

Endpoints :
- `GET /indicators/immobilier/arrondissements` — GeoJSON enrichi
- `GET /indicators/immobilier/evolution` — séries temporelles

---

## Ajouter un indicateur

1. Créer `pipeline/ingestion/mon_indicateur.py` → `load_to_bronze(df, "table_name")`
2. Créer `pipeline/transformation/mon_indicateur.py` → `load_to_silver(df, "table_name")`
3. Créer `pipeline/indicators/mon_indicateur.py` → `load_to_gold(df, "table_name")`
4. Créer `api/routes/mon_indicateur.py` et l'inclure dans `api/main.py`
5. Ajouter les appels dans `start.sh` sous `--pipeline`
