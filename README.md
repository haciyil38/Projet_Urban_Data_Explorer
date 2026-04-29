# Urban Data Explorer — Paris

Dashboard interactif d'indicateurs urbains parisiens, construit sur une architecture **Bronze / Silver / Gold** (lakehouse) avec PostgreSQL/PostGIS et MongoDB.

---

## Architecture globale

```
┌─────────────────────────────────────────────────────────────────┐
│                        SOURCES DE DONNÉES                        │
│  Paris OpenData · DVF · INSEE · GBFS Smovengo · FINESS IDF      │
│  OpenStreetMap · Copernicus ERA5-Land · RNA · data.gouv.fr       │
└───────────────────────┬─────────────────────────────────────────┘
                        │ ingestion/
                        ▼
┌─────────────────────────────────────────────────────────────────┐
│  BRONZE — PostgreSQL (schéma bronze)                             │
│  Données brutes, non transformées, historisées                   │
└───────────────────────┬─────────────────────────────────────────┘
                        │ transformation/
                        ▼
┌─────────────────────────────────────────────────────────────────┐
│  SILVER — PostgreSQL + PostGIS (schéma silver)                   │
│  Points géospatiaux (GIST), données nettoyées et normalisées     │
└───────────────────────┬─────────────────────────────────────────┘
                        │ indicators/
                        ▼
┌──────────────────────────────────────────────────────────────────┐
│  GOLD                                                             │
│  ├── PostgreSQL — fonctions PL/pgSQL (score à la demande GPS)    │
│  └── MongoDB    — agrégats et scores par arrondissement          │
└───────────────────────┬──────────────────────────────────────────┘
                        │
              ┌─────────┴──────────┐
              │   FastAPI (REST)    │
              └─────────┬──────────┘
                        │
              ┌─────────┴──────────┐
              │  MapLibre GL JS     │
              │  (dashboard Paris)  │
              └────────────────────┘
```

### Orchestration

Les pipelines de données sont orchestrés par **Prefect** avec des planifications différenciées selon la volatilité des données :

| Flow | Fréquence | Raison |
|---|---|---|
| Pipeline Vélib | Toutes les heures | Données temps réel (stocks stations) |
| Pipeline Vitalité Culturelle | Chaque nuit à 2h | Événements mis à jour quotidiennement |
| Pipeline Canicule | Chaque nuit à 3h | Fontaines pouvant changer |
| Pipeline Immobilier | Dimanche à 3h | DVF mis à jour trimestriellement |
| Pipeline Accessibilité | Dimanche à 4h | Équipements stables |

---

## Indicateurs

### 1. Vitalité Culturelle Locale

Score 0–100 calculé **à la demande** autour d'un point GPS et rayon via PostGIS `ST_DWithin`.

| Composante | Poids | Source |
|---|---|---|
| Événements culturels | 35% | Paris OpenData / OpenAgenda |
| Équipements sportifs | 25% | data.gouv.fr |
| Lieux culturels | 20% | data.culture.gouv.fr |
| Associations | 20% | RNA (Répertoire National des Associations) |

`GET /indicators/vitalite-culturelle?lat=48.86&lon=2.35&radius_m=500`

---

### 2. Immobilier

Choroplèthe par arrondissement — prix médian au m², évolution annuelle, revenus médians, logements sociaux. Données Gold stockées dans **MongoDB**.

| Donnée | Source |
|---|---|
| Prix m² médian (2021–2025) | DVF — Demandes de Valeurs Foncières |
| Revenus médians | INSEE Filosofi |
| Logements sociaux | RPLS (data.gouv.fr) |

`GET /indicators/immobilier/arrondissements` · `GET /indicators/immobilier/evolution`

---

### 3. Disponibilité Vélib

Score 0–100 calculé à la demande (densité de stations + taux de disponibilité), données **temps réel**.

| Composante | Poids | Source |
|---|---|---|
| Densité de stations dans le rayon | 50% | GBFS Smovengo (temps réel) |
| Taux de disponibilité moyen | 50% | GBFS Smovengo (temps réel) |

`GET /indicators/velib?lat=48.86&lon=2.35&radius_m=500`

---

### 4. Indice de Confort Caniculaire

Score 0–100 calculé à la demande combinant refuges frais, couverture arborée et température de surface.

| Composante | Poids | Source |
|---|---|---|
| Refuges frais dans le rayon (fontaines, espaces verts, îlots) | 35% | Paris OpenData (3 datasets) |
| Couverture arborée de l'arrondissement | 35% | Paris OpenData (200 000+ arbres) |
| Température de surface estivale (LST) | 30% | Copernicus ERA5-Land (NetCDF) |

`GET /indicators/canicule?lat=48.86&lon=2.35&radius_m=500`

> **Données ERA5-Land** : fichier NetCDF à télécharger manuellement depuis [Copernicus CDS](https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land) (variable `skt`, mois estivaux) et à placer dans `data/bronze/`.

---

### 5. AccessScore — Accessibilité aux Services

Score 0–100 basé sur la distance aux services du quotidien via décroissance exponentielle. Supporte **4 profils** de pondération.

| Catégorie | λ (tolérance) | Poids standard | Source |
|---|---|---|---|
| Commerces alimentaires | 1/230 m | 25% | OpenStreetMap Overpass |
| Médecins / centres de santé | 1/700 m | 30% | FINESS Île-de-France |
| Hôpitaux / urgences | 1/2300 m | 25% | FINESS Île-de-France |
| Écoles maternelles/élémentaires | 1/350 m | 20% | OpenStreetMap Overpass |

Profils : `standard` · `famille` (×1.5 écoles) · `senior` (×1.5 médecins) · `actif` (×1.3 commerces)

`GET /indicators/accessibilite-services?lat=48.86&lon=2.35&profile=famille&radius=1000`

---

## Prérequis

- **Docker Desktop** (PostgreSQL/PostGIS + MongoDB)
- **Python 3.11+**
- **Git** avec **Git LFS**

---

## Installation

### 1. Cloner le dépôt

```bash
git clone https://github.com/haciyil38/Projet_Urban_Data_Explorer
cd "Projet Data Archi"
git lfs pull
```

### 2. Virtualenv et dépendances

```bash
python3 -m venv .venv
source .venv/bin/activate        # macOS / Linux
# .venv\Scripts\activate         # Windows
pip install -r requirements.txt
```

### 3. Configuration

```bash
cp .env.example .env
```

Le fichier `.env` par défaut fonctionne tel quel avec Docker.

### 4. Données à placer manuellement

| Fichier | Chemin | Source |
|---|---|---|
| ERA5-Land NetCDF (température LST) | `data/bronze/<hash>.nc` | [Copernicus CDS](https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land) — variable `skt`, mois juin–août |
| RNA Associations (dpt 75) | `data/bronze/rna_import_<date>/rna_import_<date>_dpt_75.csv` | [data.gouv.fr — RNA](https://www.data.gouv.fr/fr/datasets/repertoire-national-des-associations/) |
| Populations légales INSEE *(optionnel)* | `data/referentiel/ensemble/donnees_communes.csv` | [insee.fr — Populations légales](https://www.insee.fr/fr/statistiques/2011101) |

> Toutes les autres sources sont téléchargées automatiquement par le pipeline.

---

## Démarrage

```bash
# Base de données + API + frontend uniquement
./start.sh

# Recharger toutes les données + démarrer
./start.sh --pipeline

# Avec orchestration Prefect (planifications automatiques)
./start.sh --orchestration

# Tout à la fois
./start.sh --pipeline --orchestration
```

| Service | URL |
|---|---|
| **Dashboard** | http://127.0.0.1:8080/frontend/public/index.html |
| **API Swagger** | http://127.0.0.1:8000/docs |
| **Prefect UI** | http://127.0.0.1:4200 *(si --orchestration)* |

Arrêt : `Ctrl+C`

---

## Structure du projet

```
.
├── pipeline/
│   ├── ingestion/                  # Bronze — récupération données brutes
│   │   ├── vitalite_culturelle.py  # Paris OpenData + data.culture.gouv.fr
│   │   ├── immobilier.py           # DVF + RPLS + INSEE Filosofi
│   │   ├── velib.py                # GBFS Smovengo (temps réel)
│   │   ├── canicule.py             # Paris OpenData + ERA5-Land NetCDF
│   │   └── accessibilite_services.py  # FINESS IDF + OSM Overpass
│   ├── transformation/             # Silver — nettoyage + PostGIS
│   ├── indicators/                 # Gold — fonctions SQL + sync MongoDB
│   ├── flows/                      # Prefect — orchestration planifiée
│   │   ├── velib_flow.py           # Horaire
│   │   ├── culture_flow.py         # Quotidien 2h
│   │   ├── canicule_flow.py        # Quotidien 3h
│   │   ├── immobilier_flow.py      # Hebdomadaire dim. 3h
│   │   ├── access_flow.py          # Hebdomadaire dim. 4h
│   │   └── main_flow.py            # Full pipeline (manuel)
│   ├── config.py                   # Paramètres globaux et poids indicateurs
│   └── db.py                       # Helpers PostgreSQL + MongoDB
├── api/
│   ├── main.py                     # FastAPI + CORS + rate limiting
│   ├── security.py                 # API Key + slowapi
│   └── routes/                     # Un fichier par indicateur
├── frontend/
│   ├── public/index.html           # Dashboard (5 onglets + cartes résumé)
│   └── src/
│       ├── map/                    # MapLibre GL JS par indicateur
│       └── components/style.css
├── data/
│   ├── bronze/                     # Données brutes (non versionnées)
│   └── static/                     # Fichiers de référence (LFS)
├── docker-compose.yml              # PostgreSQL/PostGIS (5433) + MongoDB (27017)
├── start.sh                        # Script de démarrage unifié
└── requirements.txt
```

---

## Sécurité API

Toutes les routes sont protégées par :
- **API Key** — header `X-API-Key: urban-data-explorer-2024`
- **Rate limiting** — 60 requêtes/minute par IP (slowapi)
- **CORS restreint** — origines autorisées : `localhost:8080` / `127.0.0.1:8080` uniquement

---

## Bases de données

### PostgreSQL + PostGIS (port 5433)

| Schéma | Contenu |
|---|---|
| `bronze` | Données brutes importées (une table par source) |
| `silver` | Données nettoyées avec géométries PostGIS + index GIST |
| `gold` | Fonctions PL/pgSQL de scoring à la demande |

### MongoDB (port 27017)

| Base | Collection | Contenu |
|---|---|---|
| `paris_gold` | `immo_arrondissement` | Scores immobiliers par arrondissement |
| `paris_gold` | `immo_evolution` | Séries temporelles prix m² |
| `paris_gold` | `vitalite_stats_reference` | Statistiques de référence Paris (totaux pour normalisation) |
| `paris_gold` | `vitalite_arrondissement` | Score vitalité culturelle par arrondissement (rayon 1 km) |
| `paris_gold` | `canicule_arrondissement` | Score confort caniculaire par arrondissement (rayon 1 km) |
| `paris_gold` | `velib_arrondissement` | Score Vélib par arrondissement (rayon 1 km) |
| `paris_gold` | `access_par_arrondissement` | AccessScore par arrondissement (profil standard, rayon 1 km) |

---

## Déclencher un pipeline manuellement (Prefect)

```bash
# Configurer le client Prefect (une seule fois)
.venv/bin/prefect config set PREFECT_API_URL=http://127.0.0.1:4200/api

# Lancer un flow
.venv/bin/prefect deployment run 'Pipeline Vélib/velib-hourly'
.venv/bin/prefect deployment run 'Pipeline Vitalité Culturelle/culture-daily'
.venv/bin/prefect deployment run 'Pipeline Canicule/canicule-daily'
.venv/bin/prefect deployment run 'Pipeline Immobilier/immobilier-weekly'
.venv/bin/prefect deployment run 'Pipeline Accessibilité Services/access-weekly'

# Ou lancer tous les pipelines en une fois
.venv/bin/python -m pipeline.flows.main_flow
```

---

## Contributeurs

| Indicateur | Auteur |
|---|---|
| Vitalité Culturelle | Équipe |
| Immobilier | Équipe |
| Vélib | Équipe |
| Canicule | Équipe |
| AccessScore | DZjeff05 (intégré depuis `dev-score-access`) |
