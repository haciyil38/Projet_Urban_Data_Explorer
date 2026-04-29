from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from pipeline.db import get_engine
from pipeline.config import ALLOWED_ORIGINS
from sqlalchemy import text

from api.security import limiter
from api.routes import vitalite_culturelle, immobilier, velib, canicule, accessibilite_services


@asynccontextmanager
async def lifespan(app: FastAPI):
    from pipeline.db import init_schemas
    from pipeline.indicators.vitalite_culturelle import setup as setup_culture
    from pipeline.indicators.velib import setup as setup_velib
    from pipeline.indicators.canicule import setup as setup_canicule
    init_schemas()
    try:
        setup_culture()
    except Exception as e:
        print(f"[WARN] setup vitalite_culturelle : {e}")
    try:
        setup_velib()
    except Exception as e:
        print(f"[WARN] setup velib : {e}")
    try:
        setup_canicule()
    except Exception as e:
        print(f"[WARN] setup canicule : {e}")
    from pipeline.indicators.accessibilite_services import setup as setup_access
    try:
        setup_access()
    except Exception as e:
        print(f"[WARN] setup accessibilite : {e}")
    yield


app = FastAPI(
    lifespan=lifespan,
    title="Urban Data Explorer API",
    description="API de scoring urbain pour Paris — calcul à la demande par point GPS et rayon.",
    version="1.0.0",
)

# ── Rate limiting ──────────────────────────────────────────────────────────
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── CORS — origines autorisées uniquement ──────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["X-API-Key", "Content-Type"],
)

app.include_router(vitalite_culturelle.router)
app.include_router(immobilier.router)
app.include_router(velib.router)
app.include_router(canicule.router)
app.include_router(accessibilite_services.router)


@app.get("/health", tags=["System"], summary="État de l'API")
@limiter.limit("30/minute")
def health(request: Request):
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
