"""
Flow Immobilier — données DVF + INSEE, rarement mises à jour.
Planifié chaque dimanche à 3h.
"""

from prefect import flow, task
from prefect.schedules import Cron

from pipeline.ingestion import immobilier as ingest
from pipeline.transformation import immobilier as transform
from pipeline.indicators import immobilier as indicator


@task(name="Ingestion DVF + logements sociaux + revenus INSEE", retries=2, retry_delay_seconds=120)
def ingest_immobilier():
    ingest.run()


@task(name="Transformation silver — prix m², accessibilité")
def transform_immobilier():
    transform.run()


@task(name="Gold immobilier → MongoDB")
def setup_immobilier():
    indicator.compute()


@flow(
    name="Pipeline Immobilier",
    description="Ingestion DVF et calcul des indicateurs immobiliers par arrondissement. Planifié chaque dimanche.",
)
def immobilier_flow():
    ingest_immobilier()
    transform_immobilier()
    setup_immobilier()


if __name__ == "__main__":
    immobilier_flow.serve(
        name="immobilier-weekly",
        schedule=Cron("0 3 * * 0"),  # dimanche 3h00
    )
