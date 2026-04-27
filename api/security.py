from fastapi import Security, HTTPException, Request
from fastapi.security.api_key import APIKeyHeader
from slowapi import Limiter
from slowapi.util import get_remote_address
from pipeline.config import API_KEY

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
limiter = Limiter(key_func=get_remote_address)


async def require_api_key(request: Request, key: str = Security(api_key_header)):
    if request.method == "OPTIONS":
        return  # Laisser passer les preflight CORS
    if key != API_KEY:
        raise HTTPException(status_code=401, detail="Clé API invalide ou manquante")
