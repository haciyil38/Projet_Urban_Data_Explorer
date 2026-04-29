# Urban Data Explorer — Contexte Présentation

Ce fichier donne à Claude tout le contexte du projet pour aider à construire les diapositives de présentation.

---

## 1. Pitch du projet

**Urban Data Explorer — Paris** est un dashboard interactif de scoring urbain qui permet à n'importe quel utilisateur de cliquer sur la carte de Paris et d'obtenir instantanément 5 scores mesurant la qualité de vie autour de ce point.

**Problème résolu** : les données de la ville de Paris sont éparpillées sur des dizaines de portails (opendata.paris.fr, data.gouv.fr, data.iledefrance.fr, data.culture.gouv.fr, Copernicus, GBFS Smovengo…). Ce projet les agrège, les nettoie, les géolocalise et les transforme en scores lisibles 0–100, calculés à la demande par point GPS et rayon.

**Cible** : citoyens, agents immobiliers, collectivités, chercheurs urbains.

---

## 2. Architecture générale — Lakehouse Bronze / Silver / Gold

```
SOURCES DE DONNÉES
  Paris OpenData · DVF/CEREMA · INSEE Filosofi · GBFS Smovengo
  FINESS Île-de-France · OpenStreetMap Overpass · Copernicus ERA5-Land
  RNA (Répertoire National des Associations) · data.culture.gouv.fr
        │
        ▼  pipeline/ingestion/
  ┌─────────────────────────────────────┐
  │  BRONZE — PostgreSQL (schéma bronze)│  données brutes, non transformées
  │  Tables : *_raw, *_agg              │  historisées (Vélib : append)
  └─────────────────────────────────────┘
        │
        ▼  pipeline/transformation/
  ┌─────────────────────────────────────┐
  │  SILVER — PostgreSQL + PostGIS      │  données nettoyées
  │  Géométries POINT (WGS84)           │  index GIST pour ST_DWithin
  │  Tables : vitalite_points_*,        │  canicule_refuges,
  │           canicule_par_arrondissement│  access_points_*, velib_stations
  └─────────────────────────────────────┘
        │
        ▼  pipeline/indicators/
  ┌──────────────────────────────────────────────────────────────────────┐
  │  GOLD                                                                 │
  │  PostgreSQL — fonctions PL/pgSQL (calcul à la demande par GPS)       │
  │    gold.score_vitalite_culturelle(lat, lon, radius_m)                │
  │    gold.score_velib(lat, lon, radius_m)                              │
  │    gold.score_canicule(lat, lon, radius_m)                           │
  │    gold.score_accessibilite_services(lat, lon, profile, radius)      │
  │  MongoDB paris_gold — agrégats pré-calculés par arrondissement       │
  │    immobilier_arrondissements, immobilier_evolution                   │
  │    vitalite_stats_reference, access_par_arrondissement               │
  └──────────────────────────────────────────────────────────────────────┘
        │
        ▼
  FastAPI (REST, port 8000) — 1 route par indicateur
        │
        ▼
  MapLibre GL JS (dashboard, port 8080) — 5 onglets + 4 cartes résumé
```

### Choix technique clé : calcul à la demande vs pré-calcul

Les scores GPS sont calculés **à la demande** en PL/pgSQL avec PostGIS (`ST_DWithin`, `ST_Distance`) : le score reflète exactement le rayon choisi par l'utilisateur. Les agrégats par arrondissement (immobilier, accessibilité) sont pré-calculés et stockés dans MongoDB pour des lectures rapides sans PostGIS.

---

## 3. Infrastructure

| Service | Image Docker | Port | Rôle |
|---|---|---|---|
| PostgreSQL + PostGIS | `postgis/postgis:16-3.4` | 5433 | Bronze + Silver + Gold SQL |
| MongoDB | `mongo:6.0` | 27017 | Gold agrégats + Bronze datalake |
| Redis | `redis:7-alpine` | 6379 | (réservé cache futur) |
| FastAPI (uvicorn) | Python 3.11+ | 8000 | API REST |
| HTTP server | `python -m http.server` | 8080 | Frontend statique |
| Prefect server | Python | 4200 | Orchestration planifiée |

**PostgreSQL backend Prefect** : le serveur Prefect utilise PostgreSQL (base `prefect`) au lieu de SQLite pour éviter les conflits de verrous entre les 5 processus de flow parallèles.

---

## 4. Les 5 indicateurs

### 4.1 Vitalité Culturelle Locale

**Score 0–100** calculé à la demande autour d'un point GPS et rayon.

**Méthode de normalisation** : densité relative à la moyenne parisienne.
```
score_i = min(100, count_rayon / count_attendu × 50)
count_attendu = total_paris × (π·r²) / surface_paris
```
→ score 50 = densité égale à la moyenne parisienne ; score 100 = double.

| Composante | Poids | Source | API |
|---|---|---|---|
| Événements culturels | 35% | Paris OpenData — "Que Faire à Paris" | opendata.paris.fr |
| Lieux culturels | 35% | Ministère Culture — Base Basilic | data.culture.gouv.fr |
| Équipements sportifs | 15% | Paris OpenData — créneaux sportifs | opendata.paris.fr |
| Associations | 15% | RNA dpt 75 (CSV ~100 Mo) | data.gouv.fr |

**Tables Silver** : `vitalite_points_evenements`, `vitalite_points_culturels`, `vitalite_points_sport`, `vitalite_points_associations`, `vitalite_stats_reference`

**MongoDB Gold** : `vitalite_stats_reference` (totaux Paris pour normalisation)

**Endpoint** : `GET /indicators/vitalite-culturelle?lat=48.86&lon=2.35&radius_m=500`

**Réponse** : `score`, `nb_evenements`, `nb_culturels`, `nb_sport`, `nb_associations`, scores détaillés par composante.

---

### 4.2 Immobilier

**Choroplèthe par arrondissement** — données pré-calculées dans MongoDB.

| Donnée | Source | URL |
|---|---|---|
| Prix médian m² 2021–2025 | DVF — data.gouv.fr (CSV.gz par année, ~50 Mo/an) | files.data.gouv.fr/geo-dvf |
| Évolution annuelle | DVF (même source) | — |
| Revenus médians | INSEE Filosofi 2021 (ZIP) | insee.fr |
| Logements sociaux | RPLS — API DiDo SDES | data.statistiques.dev-durable.gouv.fr |

**Particularité DVF** : 5 années (2021–2025) téléchargées en CSV.gz, filtrées sur dep=75, agrégées par arrondissement (code commune 751XX), prix médian calculé sur les seules ventes d'appartements/maisons avec surface renseignée.

**Endpoints** :
- `GET /indicators/immobilier/arrondissements` → prix médian, logements sociaux, revenus
- `GET /indicators/immobilier/evolution` → série temporelle prix m² par arrondissement

---

### 4.3 Disponibilité Vélib (temps réel)

**Score 0–100** = 50% score densité + 50% score disponibilité, calculé à la demande.

```
score_densité    = min(100, nb_stations_rayon / nb_attendu × 50)
score_disponibilité = avg(taux_disponibilite) × 100
```

**Source** : GBFS Smovengo — `https://velib-metropole-opendata.smovengo.fr/opendata/Velib_Metropole/station_status.json`

**Ingestion horaire** : les stocks (vélos méca + électriques, bornes dispo) sont ingérés toutes les heures via Prefect (`Interval(timedelta(hours=1))`). Chargement en mode **append** (historique conservé).

**Table Silver** : `velib_stations` avec `geom GEOMETRY(POINT, 4326)` + index GIST + `taux_disponibilite FLOAT`.

**Endpoint** : `GET /indicators/velib?lat=48.86&lon=2.35&radius_m=500`

**Réponse** : `score`, `nb_stations`, `total_velos_dispo`, `total_velos_meca`, `total_velos_elec`, `total_bornes_dispo`, `taux_moyen`, `score_densite`, `score_disponibilite`.

---

### 4.4 Indice de Confort Caniculaire

**Score 0–100** calculé à la demande via une fonction PL/pgSQL complexe.

| Composante | Poids | Source |
|---|---|---|
| Refuges frais dans le rayon | 35% | Paris OpenData : îlots fraîcheur équipements + espaces verts + fontaines à boire |
| Couverture arborée de l'arrondissement | 35% | Paris OpenData — 200 000+ arbres géolocalisés (agrégation côté serveur) |
| LST estivale (température de surface) | 30% | Copernicus ERA5-Land NetCDF — variable `skt`, mois juin–août 2022–2024 |

**Score refuges** : comparaison au nombre attendu selon la densité Paris × surface du cercle.
**Score arboré** : densité = `nb_arbres × circ_moy_cm / surface_arrondissement`, normalisé par le max Paris.
**Score LST** : inversé (plus frais = meilleur), normalisé min/max Paris. Si LST absente : redistribution 50/50 refuge/arboré.

**ERA5-Land** : fichier NetCDF téléchargé manuellement depuis Copernicus CDS. Interpolation bilinéaire au centroïde de chaque arrondissement (`xarray.interp`). Conversion Kelvin → Celsius.

**Tables Silver** : `canicule_refuges` (3 types : fontaine, ilot_equip, espace_vert), `canicule_par_arrondissement` (nb_arbres, circ_moy_cm, surface_m2, lst_ete_moy_c, centroid_lat/lon).

**Endpoint** : `GET /indicators/canicule?lat=48.86&lon=2.35&radius_m=500`

**Réponse** : `score`, `nb_refuges`, `nb_fontaines`, `nb_ilots_equip`, `nb_espaces_verts`, `nb_arbres`, `circ_moy_cm`, `lst_ete_moy_c`, `score_refuges`, `score_arboree`, `score_lst`.

---

### 4.5 AccessScore — Accessibilité aux Services

**Score 0–100** basé sur décroissance exponentielle de la distance au plus proche service.

**Formule** : `score_i = e^(-λᵢ × distance_i)` (0 si hors rayon), puis pondération.

| Catégorie | λ (tolérance) | Poids std | Source | Volume Paris |
|---|---|---|---|---|
| Commerces alimentaires | 1/230 m (~230m tolérance) | 25% | OSM Overpass | ~6 400 points |
| Médecins / centres de santé | 1/700 m (~700m tolérance) | 30% | FINESS Île-de-France | ~379 établissements |
| Hôpitaux / urgences | 1/2300 m (~2,3 km tolérance) | 25% | FINESS Île-de-France | ~92 établissements |
| Écoles maternelles/élémentaires | 1/350 m (~350m tolérance) | 20% | OSM Overpass | ~1 700 points |

**4 profils de pondération** (renormalisés après ajustement) :
- `standard` : poids par défaut
- `famille` : ×1.5 écoles, ×0.8 médecins
- `senior` : ×1.5 médecins, ×1.2 hôpitaux
- `actif` : ×1.3 commerces, ×0.5 écoles

**Sources réelles** :
- FINESS IDF : `data.iledefrance.fr/api/explore/v2.1/catalog/datasets/finess/records` — filtre `dep_code="75"` + catégories établissement (CHR, CH, MCO pour hôpitaux ; centres de santé libéraux pour médecins)
- OSM Overpass : `overpass.kumi.systems/api/interpreter` — bbox Paris `48.81,2.22,48.91,2.42`

**Tables Silver** : `access_points_commerces`, `access_points_medecins`, `access_points_hopitaux`, `access_points_ecoles` — chacune avec `geom GEOMETRY(POINT, 4326)` + index GIST.

**MongoDB Gold** : `access_par_arrondissement` — AccessScore pré-calculé au centroïde de chaque arrondissement (profil standard, rayon 1 km).

**Endpoint** : `GET /indicators/accessibilite-services?lat=48.86&lon=2.35&profile=famille&radius=1000`

**Réponse** : `score`, distances aux 4 services, scores détaillés par catégorie.

---

## 5. Orchestration Prefect

| Flow | Schedule | Fréquence | Raison |
|---|---|---|---|
| `Pipeline Vélib` | `Interval(timedelta(hours=1))` | Horaire | Stocks temps réel |
| `Pipeline Vitalité Culturelle` | `Cron("0 2 * * *")` | Nuit 2h | Événements quotidiens |
| `Pipeline Canicule` | `Cron("0 3 * * *")` | Nuit 3h | Fontaines pouvant changer |
| `Pipeline Immobilier` | `Cron("0 3 * * 0")` | Dim. 3h | DVF trimestriel |
| `Pipeline Accessibilité` | `Cron("0 4 * * 0")` | Dim. 4h | Équipements stables |

**Chaque flow** suit le même pattern : `ingest → transform → setup_gold` (3 Prefect tasks avec `retries=2`).

**Full pipeline parallèle** (`main_flow.py`) : culture + canicule + access en parallèle, puis immobilier + vélib en parallèle.

**Backend Prefect** : PostgreSQL (base `prefect` dans le même conteneur) pour éviter les verrous SQLite multi-processus.

---

## 6. API REST (FastAPI)

**Base URL** : `http://127.0.0.1:8000`

| Route | Description |
|---|---|
| `GET /health` | État API + connexion DB |
| `GET /indicators/vitalite-culturelle` | Score vitalité (lat, lon, radius_m) |
| `GET /indicators/immobilier/arrondissements` | Prix, logements sociaux, revenus par arrondissement |
| `GET /indicators/immobilier/evolution` | Série temporelle prix m² |
| `GET /indicators/velib` | Score Vélib temps réel (lat, lon, radius_m) |
| `GET /indicators/canicule` | Score confort caniculaire (lat, lon, radius_m) |
| `GET /indicators/accessibilite-services` | AccessScore (lat, lon, profile, radius) |

**Sécurité** :
- API Key : header `X-API-Key: urban-data-explorer-2024`
- Rate limiting : 60 requêtes/minute par IP (slowapi)
- CORS restreint : uniquement `localhost:8080` / `127.0.0.1:8080`
- Preflight OPTIONS autorisé sans clé (CORS pre-flight)

**Documentation automatique** : Swagger UI à `http://127.0.0.1:8000/docs`

---

## 7. Frontend (MapLibre GL JS)

**Stack** : HTML/CSS/JS vanilla + MapLibre GL JS (pas de framework JS).

**Structure** :
- `frontend/public/index.html` — dashboard principal (5 onglets + 4 cartes résumé cliquables)
- `frontend/src/map/map.js` — carte centrale, gestion des clics GPS, `fetchAllScores()`
- `frontend/src/map/immo.js` — choroplèthe immobilier + gestion onglets
- `frontend/src/map/velib.js` — couche Vélib
- `frontend/src/map/canicule.js` — couche canicule
- `frontend/src/map/access.js` — onglet AccessScore avec sélecteur profil

**Fonctionnement** :
1. L'utilisateur clique sur la carte → marqueur placé → `fetchAllScores(lat, lng, radiusM)` appelé
2. 4 requêtes API parallèles (`Promise.allSettled`) → les 4 cartes résumé se mettent à jour simultanément
3. Chaque carte résumé est cliquable → bascule vers l'onglet détaillé correspondant
4. Les onglets détaillés affichent scores + barres de progression colorées (vert/orange/rouge) + distances/comptages

**Coloration des scores** : `scoreColor(score)` → vert (#16a34a) si ≥70, orange (#d97706) si ≥40, rouge (#dc2626) sinon.

**Carte fond** : OpenStreetMap via MapLibre GL JS (tiles OSM).

**Choroplèthe immobilier** : GeoJSON des arrondissements en source MapLibre, rempli par dégradé de couleur selon prix médian m².

---

## 8. Structure du projet

```
.
├── pipeline/
│   ├── ingestion/          # Bronze — récupération APIs + fichiers
│   │   ├── vitalite_culturelle.py   # Paris OpenData + data.culture.gouv.fr + RNA
│   │   ├── immobilier.py            # DVF CSV.gz + RPLS DiDo + INSEE Filosofi ZIP
│   │   ├── velib.py                 # GBFS Smovengo JSON temps réel
│   │   ├── canicule.py              # Paris OpenData × 3 + ERA5-Land NetCDF
│   │   └── accessibilite_services.py # FINESS IDF API + OSM Overpass
│   ├── transformation/     # Silver — nettoyage + géométries PostGIS
│   ├── indicators/         # Gold — fonctions PL/pgSQL + sync MongoDB
│   ├── flows/              # Prefect — 5 flows + main_flow parallèle
│   ├── config.py           # Poids indicateurs (WEIGHTS_*, LAMBDA_ACCESS)
│   └── db.py               # Helpers PostgreSQL + MongoDB (bronze/silver/gold)
├── api/
│   ├── main.py             # FastAPI + CORS + rate limiting + lifespan setup
│   ├── security.py         # APIKeyHeader + slowapi Limiter
│   └── routes/             # 5 fichiers (un par indicateur)
├── frontend/
│   ├── public/index.html   # Dashboard 5 onglets
│   └── src/
│       ├── map/            # JS par indicateur
│       └── components/style.css
├── data/
│   ├── bronze/             # Données brutes locales (.nc ERA5-Land, RNA CSV)
│   └── static/             # Référentiels (arrondissements.geojson) — Git LFS
├── docker-compose.yml      # PostGIS:5433 + MongoDB:27017 + Redis:6379
├── start.sh                # Démarrage unifié (--pipeline, --orchestration)
└── requirements.txt
```

---

## 9. Choix techniques et justifications

| Choix | Alternative | Raison |
|---|---|---|
| PostgreSQL + PostGIS | ElasticSearch | ST_DWithin et ST_Distance natifs, index GIST, fonctions PL/pgSQL inline |
| MongoDB pour Gold agrégats | Redis | Documents JSON flexibles, agrégats par arrondissement sans schema fixe |
| FastAPI | Flask / Django | Async natif, typage Pydantic, Swagger auto, rapidité |
| Prefect 3.x | Airflow | Déploiement local simple, `flow.serve()` sans DAG XML, UI légère |
| MapLibre GL JS | Leaflet / Deck.gl | WebGL natif (performances), tiles vectorielles, pas de dépendance Google |
| FINESS IDF API | CSV national | API paginée filtrée par département, coordonnées intégrées, mise à jour officielle |
| OSM Overpass kumi.systems | overpass-api.de | Pas de restriction géographique, accepte User-Agent Python |
| Calcul à la demande (PL/pgSQL) | Pré-calcul grille | Rayon libre choisi par l'utilisateur, pas de stockage de millions de cases |
| Backend Prefect PostgreSQL | SQLite | SQLite ne supporte pas les écritures concurrentes de 5 processus |

---

## 10. Volumes de données

| Source | Volume approximatif | Fréquence MAJ |
|---|---|---|
| Que Faire à Paris | ~9 900 événements | Quotidien |
| RNA associations Paris | ~300 000 asso. | Annuel |
| Équipements culturels Basilic | ~5 000 lieux | Mensuel |
| Vélib stations (stock) | ~1 500 stations | Temps réel (horaire) |
| DVF transactions Paris | ~50 000 ventes/an × 5 ans | Trimestriel |
| Arbres Paris | 200 000+ (agrégé) | Stable |
| Fontaines + îlots fraîcheur | ~2 000 points | Mensuel |
| FINESS médecins/hôpitaux Paris | ~471 établissements | Mensuel |
| OSM commerces + écoles Paris | ~8 100 points | Hebdomadaire |
| ERA5-Land NetCDF (LST) | ~50 Mo | Manuel (historique 2022–2024) |

---

## 11. Contributeurs et indicateurs

| Indicateur | Auteur |
|---|---|
| Vitalité Culturelle Locale | Équipe |
| Immobilier | Équipe |
| Disponibilité Vélib | Équipe |
| Indice de Confort Caniculaire | Équipe |
| AccessScore (Accessibilité Services) | DZjeff05 (intégré depuis `dev-score-access`) |

L'indicateur AccessScore a été développé par DZjeff05 dans la branche `dev-score-access`. L'intégration dans `main` a remplacé les données statiques pré-générées (LFS inaccessibles) par des appels directs aux APIs officielles FINESS IDF + OSM Overpass.

---

## 12. Points forts à mettre en avant en présentation

1. **Architecture lakehouse complète** : Bronze (brut) → Silver (nettoyé + géospatial) → Gold (scoring) — pattern industriel en miniature
2. **Données 100% réelles et officielles** : aucune donnée simulée ou générée ; toutes les sources sont des APIs publiques ou des portails open data gouvernementaux
3. **Calcul à la demande par GPS** : n'importe quel point dans Paris, n'importe quel rayon — la granularité n'est pas limitée à l'arrondissement
4. **PostGIS comme moteur de scoring** : les fonctions PL/pgSQL exécutent la géométrie directement en base (ST_DWithin, ST_Distance, EXP) — zéro aller-retour Python pour le calcul
5. **Orchestration Prefect** : les données se mettent à jour automatiquement selon la volatilité (horaire pour Vélib, hebdomadaire pour l'immobilier)
6. **Sécurité API** : API Key + rate limiting + CORS restreint — prêt pour une exposition publique
7. **Multi-profils AccessScore** : un même indicateur s'adapte au profil utilisateur (famille, senior, actif) via renormalisation des poids
8. **Données satellite ERA5-Land** : la température de surface estivale (LST) vient du programme Copernicus — données scientifiques européennes intégrées dans un dashboard citoyen
