"""payments (puerto 9004): inicio de pagos y verificación del aviso del proveedor (adaptador de prueba)."""
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

from common.config import get_secret, service_url
from common.db import init, read, tx
from common.security import Ctx, make_guard, only_callers, require_user
from common.web import add_request_logging, internal_call

DDL = """
CREATE TABLE IF NOT EXISTS payments(
  id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL, user_id TEXT NOT NULL, monto INTEGER NOT NULL,
  estado TEXT NOT NULL, provider_ref TEXT UNIQUE NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS processed_events(event_id TEXT PRIMARY KEY, at TEXT NOT NULL);
"""
guard = make_guard("PAYMENTS_SERVICE_SECRET")
app = FastAPI(title="payments", description="Pagos (privado)")
add_request_logging(app, "payments")
ORDERS = service_url("ORDERS", 9003)


@app.on_event("startup")
def startup():
    init("payments", DDL)


class PaymentIn(BaseModel):  # solo se acepta el id del pedido; el monto jamás viene del navegador
    order_id: int = Field(gt=0)


class WebhookIn(BaseModel):
    event_id: str = Field(min_length=6, max_length=64)
    provider_ref: str = Field(min_length=6, max_length=64)
    status: str = Field(pattern="^(approved|rejected)$")
    amount: int = Field(gt=0)


def get_order(order_id: int) -> dict:
    r = internal_call("GET", f"{ORDERS}/internal/orders/{order_id}", get_secret("ORDERS_SERVICE_SECRET"), caller="payments")
    if r.status_code == 404:
        raise HTTPException(404, "Pedido no encontrado")
    if r.status_code != 200:
        raise HTTPException(503, "Servicio de pedidos no disponible")
    return r.json()


@app.get("/health")
def health():
    return {"status": "OK", "service": "payments"}


@app.post("/payments", status_code=201)
def start_payment(body: PaymentIn, ctx: Ctx = Depends(guard)):
    uid = require_user(ctx)
    order = get_order(body.order_id)
    if order["user_id"] != uid:
        raise HTTPException(404, "Pedido no encontrado")
    if order["estado"] != "pendiente_pago":
        raise HTTPException(409, "El pedido no está pendiente de pago")
    with tx("payments") as c:
        prev = c.execute("SELECT * FROM payments WHERE order_id=? AND estado='iniciado'", (body.order_id,)).fetchone()
        if prev:  # idempotente: un solo pago iniciado por pedido
            return {"payment_id": prev["id"], "estado": prev["estado"], "monto": prev["monto"], "provider_ref": prev["provider_ref"]}
        ref = "prv_" + secrets.token_hex(8)
        cur = c.execute("INSERT INTO payments(order_id,user_id,monto,estado,provider_ref,created_at) VALUES(?,?,?,?,?,?)",
                        (body.order_id, uid, order["total"], "iniciado", ref, datetime.now(timezone.utc).isoformat()))
        pid = cur.lastrowid
    return {"payment_id": pid, "estado": "iniciado", "monto": order["total"], "provider_ref": ref}


@app.post("/payments/webhook")
async def webhook(request: Request, x_provider_signature: Optional[str] = Header(default=None), ctx: Ctx = Depends(guard)):
    raw = await request.body()
    expected = hmac.new(get_secret("PAYMENTS_WEBHOOK_SECRET").encode(), raw, hashlib.sha256).hexdigest()
    if not x_provider_signature or not hmac.compare_digest(x_provider_signature, expected):
        raise HTTPException(401, "Firma del proveedor inválida")
    try:
        ev = WebhookIn(**json.loads(raw))
    except Exception:
        raise HTTPException(400, "Aviso inválido")
    with tx("payments") as c:
        if c.execute("SELECT 1 FROM processed_events WHERE event_id=?", (ev.event_id,)).fetchone():
            return {"duplicate": True}  # el mismo aviso no se procesa dos veces
        pay = c.execute("SELECT * FROM payments WHERE provider_ref=?", (ev.provider_ref,)).fetchone()
        if not pay:
            raise HTTPException(404, "Pago desconocido")
        if ev.amount != pay["monto"]:
            raise HTTPException(409, "Monto no coincide con el pedido")
        if pay["estado"] != "iniciado":
            raise HTTPException(409, "El pago ya fue resuelto")
        nuevo = "aprobado" if ev.status == "approved" else "rechazado"
        if nuevo == "aprobado":  # si orders falla, se aborta la transacción y el aviso puede reintentarse
            r = internal_call("POST", f"{ORDERS}/internal/orders/{pay['order_id']}/mark-paid",
                              get_secret("ORDERS_SERVICE_SECRET"), caller="payments")
            if r.status_code != 200:
                raise HTTPException(502, "No se pudo actualizar el pedido")
        c.execute("UPDATE payments SET estado=? WHERE id=?", (nuevo, pay["id"]))
        c.execute("INSERT INTO processed_events VALUES(?,?)", (ev.event_id, datetime.now(timezone.utc).isoformat()))
    return {"duplicate": False, "estado": nuevo}


@app.get("/internal/payments/by-order/{order_id}")
def by_order(order_id: int, ctx: Ctx = Depends(guard)):
    only_callers(ctx, "graphql")
    with read("payments") as c:
        r = c.execute("SELECT estado, monto FROM payments WHERE order_id=? ORDER BY id DESC LIMIT 1", (order_id,)).fetchone()
    return dict(r) if r else {"estado": "sin_pago", "monto": 0}
