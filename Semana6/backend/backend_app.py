import os
import secrets
from fastapi import FastAPI, Header, HTTPException, Depends

app = FastAPI(title="Backend API", description="API interna protegida por gateway secret")

INTERNAL_GATEWAY_SECRET = os.getenv("INTERNAL_GATEWAY_SECRET")

if not INTERNAL_GATEWAY_SECRET:
    raise RuntimeError("INTERNAL_GATEWAY_SECRET no está configurado")



def verify_gateway(x_gateway_secret: str = Header(default="")):
    valid = secrets.compare_digest(x_gateway_secret, INTERNAL_GATEWAY_SECRET)
    if not valid:
        raise HTTPException(
            status_code=401,
            detail="Solicitud no autorizada desde gateway"
        )


@app.get("/health", dependencies=[Depends(verify_gateway)])
def health(x_authenticated_client: str = Header(default=None)):
    return {
        "status": "OK",
        "service": "Backend API",
        "authenticated_client": x_authenticated_client
    }


@app.get("/productos", dependencies=[Depends(verify_gateway)])
def productos(x_authenticated_client: str = Header(default=None)):
    return {
        "authenticated_client": x_authenticated_client,
        "productos": [
            {"id": 1, "nombre": "Roll California", "categoria": "Sushi", "precio": 6500, "disponible": True},
            {"id": 2, "nombre": "Ramen Tonkotsu", "categoria": "Sopas", "precio": 7200, "disponible": True}
        ]
    }


@app.get("/clientes", dependencies=[Depends(verify_gateway)])
def clientes(x_authenticated_client: str = Header(default=None)):
    return {
        "authenticated_client": x_authenticated_client,
        "clientes": [
            {"run": "12345678-9", "nombreCompleto": "Juan Pérez", "email": "juan@example.com", "comuna": "Providencia"}
        ]
    }