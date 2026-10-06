import os

import httpx
from fastapi import FastAPI, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

app = FastAPI(
    title="Fukusuke Sushi - API Gateway Seguro con Auth Service",
    description="Gateway perimetral con introspección de tokens en Auth Service"
)

security = HTTPBearer(auto_error=False)

AUTH_SERVICE_URL = os.getenv("AUTH_SERVICE_URL", "http://127.0.0.1:8100")
BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:9000")
VAULT_ADDR = os.getenv("VAULT_ADDR", "http://127.0.0.1:8200")
VAULT_TOKEN = os.getenv("VAULT_TOKEN", "dev-only-token")


async def get_gateway_secrets():
    """Recupera desde Vault el secreto compartido con el backend y el de introspección
    compartido con el Auth Service (ambos guardados en secret/gateway)."""
    url = f"{VAULT_ADDR}/v1/secret/data/gateway"
    headers = {"X-Vault-Token": VAULT_TOKEN}
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(url, headers=headers)
        if response.status_code != 200:
            raise HTTPException(status_code=500, detail="Fallo al conectar con Vault")
        return response.json()["data"]["data"]


async def authenticate_client(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token requerido"
        )

    vault_secrets = await get_gateway_secrets()
    introspection_secret = vault_secrets.get("auth_introspection_secret", "gateway-auth-secret-789")
    backend_secret = vault_secrets.get("backend_shared_secret")

    # Introspección de token contra el Auth-service (puerto 8100)
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"{AUTH_SERVICE_URL}/introspect",
                json={"token": credentials.credentials},
                headers={"X-Gateway-Auth-Secret": introspection_secret}
            )
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="Auth Service no disponible")

    if resp.status_code == status.HTTP_403_FORBIDDEN:
        raise HTTPException(status_code=502, detail="Gateway no autorizado por Auth Service")

    if resp.status_code != 200 or not resp.json().get("active"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido"
        )

    token_info = resp.json()

    return {
        "client_id": token_info.get("user_id", "anonymous"),
        "username": token_info.get("username"),
        "roles": token_info.get("roles", []),
        "backend_secret": backend_secret
    }


@app.get("/health")
def health():
    return {"status": "OK", "service": "API Gateway Fukusuke"}


@app.post("/api/auth/login")
async def proxy_login(request: Request):
    body = await request.body()
    async with httpx.AsyncClient(timeout=5.0) as client:
        upstream = await client.post(
            f"{AUTH_SERVICE_URL}/login",
            content=body,
            headers={"content-type": request.headers.get("content-type", "application/json")}
        )
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers={"content-type": upstream.headers.get("content-type", "application/json")}
    )


@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy(path: str, request: Request, auth=Depends(authenticate_client)):
    target_url = f"{BACKEND_URL}/{path}"
    body = await request.body()

    gateway_headers = {
        "X-Gateway-Secret": auth["backend_secret"],
        "X-Authenticated-Client": auth["client_id"],
        "X-Client-Role": ",".join(auth["roles"])
    }

    content_type = request.headers.get("content-type")
    if content_type:
        gateway_headers["content-type"] = content_type

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            upstream = await client.request(
                method=request.method,
                url=target_url,
                params=request.query_params,
                content=body,
                headers=gateway_headers
            )
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="Backend no disponible")

    response_headers = {}
    if "content-type" in upstream.headers:
        response_headers["content-type"] = upstream.headers["content-type"]

    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=response_headers
    )
