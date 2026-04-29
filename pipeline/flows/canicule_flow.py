"""
Flow Canicule — sources Paris OpenData + ERA5-Land.
Planifié quotidiennement (fontaines peuvent changer).
LST saisonnière, arbres stables → pas besoin de plus fréquent.
"""

from prefect import flow, task
from prefect.schedules import Cron

from pipeline.ingestion import canicule as ingest
from pipeline.transformation import canicule as transform
from pipeline.indicators import canicule as indicator


@task(name="Ingestion canicule (refuges frais, arbres, LST ERA5)", retries=2, retry_delay_seconds=60)
def ingest_canicule():
    ingest.run()


@task(name="Transformation silver.canicule_refuges + par_arrondissement")
def transform_canicule():
    transform.run()


@task(name="Gold score_canicule SQL function")
def setup_canicule():
    indicator.setup()


@flow(
    name="Pipeline Canicule",
    description="Ingestion des données de confort caniculaire (refuges frais, arbres, LST). Planifié chaque nuit à 3h.",
)
def canicule_flow():
    ingest_canicule()
    transform_canicule()
    setup_canicule()


if __name__ == "__main__":
    canicule_flow.serve(
        name="canicule-daily",
        schedule=Cron("0 3 * * *"),  # 3h00 chaque nuit
    )
