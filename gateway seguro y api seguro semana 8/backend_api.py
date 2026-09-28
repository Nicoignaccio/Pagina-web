import os
import secrets
from fastapi import FastAPI, Header, HTTPException, Depends

app = FastAPI(
    title="Fukusuke Sushi - Protected Backend API",
    description="API interna de sushi protegida contra accesos directos fuera del Gateway"
)

INTERNAL_GATEWAY_SECRET = os.getenv("INTERNAL_GATEWAY_SECRET")
if not INTERNAL_GATEWAY_SECRET:
    raise RuntimeError("INTERNAL_GATEWAY_SECRET no está configurado")


def verify_gateway(x_gateway_secret: str = Header(default="")):
    valid = secrets.compare_digest(x_gateway_secret, INTERNAL_GATEWAY_SECRET)
    if not valid:
        raise HTTPException(
            status_code=403,
            detail="Solicitud no autorizada desde gateway"
        )


@app.get("/health")
def health():
    return {"status": "OK", "service": "Fukusuke Backend API"}


@app.get("/products", dependencies=[Depends(verify_gateway)])
def products(x_authenticated_client: str | None = Header(default=None)):
    return {
        "authenticated_client": x_authenticated_client,
        "products": [
            {"id": 1, "name": "Handroll Pollo Teriyaki", "price": 4500},
            {"id": 2, "name": "Tabla Fukusuke 30 piezas (Pollo/Palta)", "price": 18990}
        ]
    }


@app.get("/orders", dependencies=[Depends(verify_gateway)])
def orders(x_authenticated_client: str | None = Header(default=None)):
    return {
        "authenticated_client": x_authenticated_client,
        "orders": [
            {"id": 5001, "customer": "Cliente Maipú", "total": 23490, "status": "pending"}
        ]
    }
