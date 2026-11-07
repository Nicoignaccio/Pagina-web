"""API Gateway (puerto 8000): única entrada pública. Lista blanca de rutas, identidad, roles y límites."""
import os
import re
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Optional

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from common.config import get_secret, service_url
from common.web import add_request_logging

TARGETS = {  # servicio privado -> (url base, nombre del secreto que el gateway presenta)
    "inventory": (service_url("INVENTORY", 9001), "INVENTORY_SERVICE_SECRET"),
    "clients": (service_url("CLIENTS", 9002), "CLIENTS_SERVICE_SECRET"),
    "orders": (service_url("ORDERS", 9003), "ORDERS_SERVICE_SECRET"),
    "payments": (service_url("PAYMENTS", 9004), "PAYMENTS_SERVICE_SECRET"),
    "graphql": (service_url("GRAPHQL", 9005), "GRAPHQL_SERVICE_SECRET"),
}
AUTH_URL = service_url("AUTH", 8100)
MAX_BODY = 64 * 1024


@dataclass(frozen=True)
class Route:
    id: str
    method: str
    pattern: str
    access: str  # anon | auth | admin | staff | provider
    target: str
    path: str


ROUTES = [
    Route("S01", "GET", r"/products", "anon", "inventory", "/products"),
    Route("S02", "GET", r"/products/(\d+)", "anon", "inventory", "/products/{0}"),
    Route("S03", "POST", r"/products", "admin", "inventory", "/products"),
    Route("S04", "PUT", r"/products/(\d+)", "admin", "inventory", "/products/{0}"),
    Route("S05", "GET", r"/clients/me", "auth", "clients", "/clients/me"),
    Route("S06", "PUT", r"/clients/me", "auth", "clients", "/clients/me"),
    Route("S07", "GET", r"/clients", "admin", "clients", "/clients"),
    Route("S08", "POST", r"/orders", "auth", "orders", "/orders"),
    Route("S09", "GET", r"/orders", "auth", "orders", "/orders"),
    Route("S10", "GET", r"/orders/(\d+)", "auth", "orders", "/orders/{0}"),
    Route("S11", "DELETE", r"/orders/(\d+)", "auth", "orders", "/orders/{0}"),
    Route("S12", "PATCH", r"/orders/(\d+)/status", "staff", "orders", "/orders/{0}/status"),
    Route("S13", "POST", r"/payments", "auth", "payments", "/payments"),
    Route("S14", "POST", r"/payments/webhook", "provider", "payments", "/payments/webhook"),
    Route("S15", "POST", r"/graphql", "auth", "graphql", "/graphql"),
]
AUTH_ROUTES = {("POST", "/auth/register"): "register", ("POST", "/auth/login"): "login", ("POST", "/auth/logout"): "logout"}

app = FastAPI(title="API Gateway Fukusuke", description="Entrada pública con políticas de seguridad", docs_url=None, redoc_url=None)
add_request_logging(app, "gateway")
app.add_middleware(CORSMiddleware, allow_origins=[o for o in os.getenv("CORS_ORIGINS", "").split(",") if o],
                   allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"], allow_headers=["Authorization", "Content-Type"])

_hits: dict = defaultdict(deque)


def rate_limited(key: str, limit: int, window: int = 60) -> Optional[int]:
    q, t = _hits[key], time.time()
    while q and q[0] < t - window:
        q.popleft()
    if len(q) >= limit:
        return int(window - (t - q[0])) + 1
    q.append(t)
    return None


def err(status: int, msg: str, headers=None) -> JSONResponse:
    return JSONResponse({"detail": msg}, status_code=status, headers=headers)


def relay(r: httpx.Response) -> Response:
    if r.status_code >= 500:
        return err(502, "Servicio no disponible")  # no se propagan errores internos
    return Response(r.content, status_code=r.status_code, media_type=r.headers.get("content-type", "application/json"))


async def introspect(token: str) -> Optional[dict]:
    async with httpx.AsyncClient(timeout=3.0) as client:
        r = await client.post(f"{AUTH_URL}/introspect", json={"token": token},
                              headers={"X-Gateway-Auth-Secret": get_secret("AUTH_INTROSPECTION_SECRET")})
    if r.status_code != 200:
        raise httpx.HTTPError("auth")
    d = r.json()
    return d if d.get("active") else None


def bearer(request: Request) -> Optional[str]:
    h = request.headers.get("authorization", "")
    return h[7:].strip() if h.lower().startswith("bearer ") and len(h) > 7 else None


@app.get("/health")
def health():
    return {"status": "OK", "service": "API Gateway Fukusuke"}


@app.api_route("/api/v1/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def entry(path: str, request: Request):
    full, method = "/" + path, request.method
    ip = request.client.host if request.client else "?"
    body = await request.body()
    if len(body) > MAX_BODY:
        return err(413, "Cuerpo demasiado grande")
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    try:
        if (method, full) in AUTH_ROUTES:
            wait = rate_limited(f"auth:{ip}", int(os.getenv("RATE_LIMIT_AUTH", "10")))
            if wait:
                return err(429, "Demasiadas solicitudes", {"Retry-After": str(wait)})
            return await auth_flow(AUTH_ROUTES[(method, full)], request, body)
        route, groups = None, ()
        for r in ROUTES:
            m = re.fullmatch(r.pattern, full)
            if m and r.method == method:
                route, groups = r, m.groups()
                break
        if route is None:  # ruta o verbo fuera de la lista blanca
            return err(404, "Ruta no encontrada")
        wait = rate_limited(f"api:{ip}", int(os.getenv("RATE_LIMIT_API", "120")))
        if wait:
            return err(429, "Demasiadas solicitudes", {"Retry-After": str(wait)})
        # Se construyen cabeceras nuevas: toda cabecera de identidad aportada por el navegador se descarta.
        base, secret_name = TARGETS[route.target]
        headers = {"X-Service-Token": get_secret(secret_name), "X-Caller": "gateway", "X-Request-Id": rid}
        if route.access in ("auth", "admin", "staff"):
            token = bearer(request)
            if not token:
                return err(401, "Sesión requerida")
            who = await introspect(token)
            if not who:
                return err(401, "Sesión inválida o expirada")
            roles = set(who["roles"])
            if route.access == "admin" and "admin" not in roles:
                return err(403, "No autorizado")
            if route.access == "staff" and not roles & {"admin", "delivery"}:
                return err(403, "No autorizado")
            headers["X-User-Id"], headers["X-User-Roles"] = who["user_id"], ",".join(sorted(roles))
        if route.access == "anon" and bearer(request):  # identidad opcional: un token inválido se trata como anónimo
            who = await introspect(bearer(request))
            if who:
                headers["X-User-Id"], headers["X-User-Roles"] = who["user_id"], ",".join(sorted(who["roles"]))
        if route.access == "provider":
            headers["X-Provider-Signature"] = request.headers.get("x-provider-signature", "")
        if request.headers.get("content-type"):
            headers["Content-Type"] = request.headers["content-type"]
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.request(method, base + route.path.format(*groups), params=dict(request.query_params),
                                     content=body, headers=headers)
        return relay(r)
    except httpx.TimeoutException:
        return err(504, "Tiempo de espera agotado")
    except httpx.HTTPError:
        return err(502, "Servicio no disponible")


async def auth_flow(action: str, request: Request, body: bytes):
    gw = {"X-Gateway-Auth-Secret": get_secret("AUTH_INTROSPECTION_SECRET"), "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=5.0) as client:
        if action == "logout":
            token = bearer(request)
            if not token:
                return err(401, "Sesión requerida")
            if not await introspect(token):
                return err(401, "Sesión inválida o expirada")
            return relay(await client.post(f"{AUTH_URL}/logout", json={"token": token}, headers=gw))
        return relay(await client.post(f"{AUTH_URL}/{action}", content=body, headers=gw))
