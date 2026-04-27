from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pipeline.db import get_engine
from sqlalchemy import text

from api.routes import accessibilite_services, immobilier, vitalite_culturelle

app = FastAPI(
    title="Urban Data Explorer API",
    description="API de scoring urbain pour Paris — calcul à la demande par point GPS et rayon.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(vitalite_culturelle.router)
app.include_router(immobilier.router)
app.include_router(accessibilite_services.router)


@app.get("/health", tags=["System"], summary="État de l'API")
def health():
    """Vérifie que l'API et la base de données sont opérationnelles."""
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception as e:
        db_status = f"error: {e}"

    return {
        "status": "ok" if db_status == "ok" else "degraded",
        "database": db_status,
    }
