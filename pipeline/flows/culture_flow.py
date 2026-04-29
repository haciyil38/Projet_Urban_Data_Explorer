"""
Flow Vitalité Culturelle — données Paris OpenData, planifié quotidiennement.
"""

from prefect import flow, task
from prefect.schedules import Cron

from pipeline.ingestion import vitalite_culturelle as ingest
from pipeline.transformation import vitalite_culturelle as transform
from pipeline.indicators import vitalite_culturelle as indicator


@task(name="Ingestion culture (Paris OpenData)", retries=2, retry_delay_seconds=60)
def ingest_culture():
    ingest.run()


@task(name="Transformation silver — événements, lieux, sport, asso")
def transform_culture():
    transform.run()


@task(name="Gold score_vitalite_culturelle + sync MongoDB")
def setup_culture():
    indicator.setup()


@flow(
    name="Pipeline Vitalité Culturelle",
    description="Ingestion et transformation des données culturelles Paris. Planifié chaque nuit à 2h.",
)
def culture_flow():
    ingest_culture()
    transform_culture()
    setup_culture()


if __name__ == "__main__":
    culture_flow.serve(
        name="culture-daily",
        schedule=Cron("0 2 * * *"),  # 2h00 chaque nuit
    )
