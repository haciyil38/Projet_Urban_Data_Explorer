"""
Flow Accessibilité Services — FINESS IDF + OSM Overpass.
Planifié chaque dimanche (les équipements changent peu souvent).
"""

from prefect import flow, task
from prefect.schedules import Cron

from pipeline.ingestion import accessibilite_services as ingest
from pipeline.transformation import accessibilite_services as transform
from pipeline.indicators import accessibilite_services as indicator


@task(name="Ingestion accès (FINESS IDF + OSM Overpass)", retries=2, retry_delay_seconds=60)
def ingest_access():
    ingest.run()


@task(name="Transformation silver — commerces, médecins, hôpitaux, écoles")
def transform_access():
    transform.run()


@task(name="Gold score_accessibilite_services SQL function")
def setup_access():
    indicator.setup()


@flow(
    name="Pipeline Accessibilité Services",
    description="Ingestion FINESS (hôpitaux, centres santé) + OSM (commerces, écoles). Planifié chaque dimanche.",
)
def access_flow():
    ingest_access()
    transform_access()
    setup_access()


if __name__ == "__main__":
    access_flow.serve(
        name="access-weekly",
        schedule=Cron("0 4 * * 0"),  # dimanche 4h00
    )
