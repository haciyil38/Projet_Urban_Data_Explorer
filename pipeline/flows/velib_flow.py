"""
Flow Vélib — données temps réel, rafraîchissement toutes les heures.
"""

from datetime import timedelta

from prefect import flow, task
from prefect.schedules import Interval

from pipeline.ingestion import velib as ingest
from pipeline.transformation import velib as transform
from pipeline.indicators import velib as indicator


@task(name="Ingestion Vélib (GBFS Smovengo)", retries=2, retry_delay_seconds=30)
def ingest_velib():
    ingest.run()


@task(name="Transformation silver.velib_stations")
def transform_velib():
    transform.run()


@task(name="Gold score_velib SQL function")
def setup_velib():
    indicator.setup()


@flow(
    name="Pipeline Vélib",
    description="Re-fetch des stations Vélib temps réel (GBFS). Planifié toutes les heures.",
)
def velib_flow():
    ingest_velib()
    transform_velib()
    setup_velib()


if __name__ == "__main__":
    velib_flow.serve(
        name="velib-hourly",
        schedule=Interval(timedelta(hours=1)),
        limit=1,
    )
