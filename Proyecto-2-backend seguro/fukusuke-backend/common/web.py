"""Utilidades web: logging con correlación (sin secretos) y cliente HTTP interno."""
import logging
import time
import uuid

import httpx
from fastapi import FastAPI, HTTPException, Request

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def add_request_logging(app: FastAPI, service: str) -> None:
    log = logging.getLogger(service)

    @app.middleware("http")
    async def _log(request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        t0 = time.time()
        response = await call_next(request)
        response.headers["X-Request-Id"] = rid
        # Solo método, ruta (sin query) y estado: nunca cabeceras, cuerpos ni tokens.
        log.info("rid=%s %s %s -> %s %.0fms", rid, request.method, request.url.path,
                 response.status_code, (time.time() - t0) * 1000)
        return response


def internal_call(method: str, url: str, secret: str, *, caller: str, user_id=None, roles="",
                  json=None, params=None, rid=None, timeout: float = 3.0):
    """Llamada sincrónica a un servicio privado. Errores de red -> 503 controlado."""
    headers = {"X-Service-Token": secret, "X-Caller": caller}
    if user_id:
        headers["X-User-Id"] = user_id
        headers["X-User-Roles"] = roles
    if rid:
        headers["X-Request-Id"] = rid
    try:
        return httpx.request(method, url, headers=headers, json=json, params=params, timeout=timeout)
    except httpx.HTTPError:
        raise HTTPException(503, "Servicio dependiente no disponible")
