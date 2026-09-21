import os
import httpx
from fastapi import FastAPI, Request, Header, HTTPException, Depends
from fastapi.responses import Response

app = FastAPI(title="Local API Gateway", description="Gateway con secretos gestionados por Vault")

BACKEND_URL = "http://127.0.0.1:9000"

VAULT_ADDR = os.getenv("VAULT_ADDR", "http://127.0.0.1:8200")
VAULT_TOKEN = os.getenv("VAULT_TOKEN")

if not VAULT_TOKEN:
    raise RuntimeError("VAULT_TOKEN no está configurado")


def get_secret_from_vault():
    url = f"{VAULT_ADDR}/v1/secret/data/gateway"
    headers = {"X-Vault-Token": VAULT_TOKEN}
    with httpx.Client() as client:
        response = client.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()["data"]["data"]
    return data


secret_data = get_secret_from_vault()
BACKEND_SHARED_SECRET = secret_data["backend_shared_secret"]
CLIENT_TOKEN = secret_data["client_token"]


def authenticate_client(authorization: str = Header(default="")):
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bearer token requerido")

    token = authorization.removeprefix("Bearer ").strip()
    valid = token == CLIENT_TOKEN

    if not valid:
        raise HTTPException(status_code=401, detail="Token de cliente inválido")

    return token  # client_id



@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy(path: str, request: Request, client_id: str = Depends(authenticate_client)):
    target_url = f"{BACKEND_URL}/{path}"
    body = await request.body()

    headers = {
        "X-Gateway-Secret": BACKEND_SHARED_SECRET,
        "X-Authenticated-Client": client_id,
    }
    content_type = request.headers.get("content-type")
    if content_type:
        headers["Content-Type"] = content_type

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            upstream = await client.request(
                request.method,
                target_url,
                params=request.query_params,
                content=body,
                headers=headers,
            )
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="Backend no disponible")

    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=dict(upstream.headers),
    )