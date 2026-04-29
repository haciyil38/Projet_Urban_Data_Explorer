"""
Flow principal — charge tous les indicateurs en une seule passe.
Usage : python -m pipeline.flows.main_flow
"""

from prefect import flow
from prefect.futures import wait

from pipeline.flows.culture_flow import culture_flow
from pipeline.flows.immobilier_flow import immobilier_flow
from pipeline.flows.canicule_flow import canicule_flow
from pipeline.flows.velib_flow import velib_flow
from pipeline.flows.access_flow import access_flow


@flow(
    name="Urban Data Explorer — Full Pipeline",
    description="Charge tous les indicateurs depuis zéro. Parallélisme maximal entre flows indépendants.",
)
def full_pipeline():
    # Culture, canicule et access sont indépendants : parallèle
    f_culture  = culture_flow(return_state=True)
    f_canicule = canicule_flow(return_state=True)
    f_access   = access_flow(return_state=True)
    wait([f_culture, f_canicule, f_access])

    # Immobilier et vélib aussi indépendants entre eux
    f_immo  = immobilier_flow(return_state=True)
    f_velib = velib_flow(return_state=True)
    wait([f_immo, f_velib])


if __name__ == "__main__":
    full_pipeline()
