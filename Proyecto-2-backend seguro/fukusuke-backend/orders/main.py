"""orders (puerto 9003): pedidos y ciclo de vida. Autoridad única del estado del pedido."""
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from common.config import get_secret, service_url
from common.db import init, read, tx
from common.messaging import publish_event
from common.security import Ctx, make_guard, only_callers, require_user
from common.web import add_request_logging, internal_call

DDL = """
CREATE TABLE IF NOT EXISTS orders(
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, estado TEXT NOT NULL, total INTEGER NOT NULL,
  direccion_entrega TEXT NOT NULL, comuna TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS order_items(
  id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL REFERENCES orders(id),
  product_id INTEGER NOT NULL, nombre TEXT NOT NULL, precio_unit INTEGER NOT NULL, cantidad INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS order_history(
  id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL REFERENCES orders(id),
  estado TEXT NOT NULL, actor TEXT NOT NULL, at TEXT NOT NULL);
"""
# estado actual -> {nuevo estado: roles que pueden provocar la transición}
TRANSITIONS = {
    "pendiente_pago": {"anulado": {"owner", "admin"}},
    "pagado": {"en_preparacion": {"admin"}, "anulado": {"admin"}},
    "en_preparacion": {"despachado": {"admin"}, "anulado": {"admin"}},
    "despachado": {"entregado": {"admin", "delivery"}},
}
guard = make_guard("ORDERS_SERVICE_SECRET")
app = FastAPI(title="orders", description="Pedidos (privado)")
add_request_logging(app, "orders")
INVENTORY, CLIENTS = service_url("INVENTORY", 9001), service_url("CLIENTS", 9002)


@app.on_event("startup")
def startup():
    init("orders", DDL)


class Item(BaseModel):
    product_id: int
    cantidad: int = Field(ge=1, le=20)


class OrderIn(BaseModel):  # campos extra (total, estado, precios) se ignoran: el servidor calcula
    items: List[Item] = Field(min_length=1, max_length=20)


class StatusIn(BaseModel):
    estado: str


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load(order_id: int) -> Optional[dict]:
    with read("orders") as c:
        o = c.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        if not o:
            return None
        items = c.execute("SELECT product_id,nombre,precio_unit,cantidad FROM order_items WHERE order_id=?", (order_id,)).fetchall()
    d = dict(o)
    d["items"] = [dict(i) for i in items]
    return d


def view_for(o: dict, ctx: Ctx) -> dict:
    """DTO hacia el frontend: sin datos internos innecesarios."""
    return {"id": o["id"], "estado": o["estado"], "total": o["total"], "created_at": o["created_at"],
            "direccion_entrega": o["direccion_entrega"], "comuna": o["comuna"], "items": o["items"]}


def visible_or_404(order_id: int, ctx: Ctx) -> dict:
    o = load(order_id)
    if not o or not (o["user_id"] == ctx.user_id or ctx.is_staff):
        raise HTTPException(404, "Pedido no encontrado")  # 404 también para ajenos: evita enumerar ids
    return o


def set_state(c, order_id: int, estado: str, actor: str) -> None:
    c.execute("UPDATE orders SET estado=?, updated_at=? WHERE id=?", (estado, now(), order_id))
    c.execute("INSERT INTO order_history(order_id,estado,actor,at) VALUES(?,?,?,?)", (order_id, estado, actor, now()))


def release_stock(o: dict) -> None:
    internal_call("POST", f"{INVENTORY}/internal/release", get_secret("INVENTORY_SERVICE_SECRET"), caller="orders",
                  json={"items": [{"product_id": i["product_id"], "cantidad": i["cantidad"]} for i in o["items"]]})


@app.get("/health")
def health():
    return {"status": "OK", "service": "orders"}


@app.post("/orders", status_code=201)
def create_order(body: OrderIn, ctx: Ctx = Depends(guard)):
    uid = require_user(ctx)
    r = internal_call("GET", f"{CLIENTS}/internal/clients/{uid}", get_secret("CLIENTS_SERVICE_SECRET"), caller="orders")
    if r.status_code == 404:
        raise HTTPException(409, "Debe completar su perfil de cliente antes de pedir")
    r.raise_for_status()
    perfil = r.json()
    res = internal_call("POST", f"{INVENTORY}/internal/reserve", get_secret("INVENTORY_SERVICE_SECRET"), caller="orders",
                        json={"items": [i.model_dump() for i in body.items]})
    if res.status_code != 200:
        raise HTTPException(res.status_code if res.status_code in (409, 503) else 502,
                            res.json().get("detail", "Inventario no disponible") if res.status_code == 409 else "Inventario no disponible")
    lines = res.json()["items"]
    total = sum(l["precio_unit"] * l["cantidad"] for l in lines)  # precios de inventory, no del navegador
    try:
        with tx("orders") as c:
            cur = c.execute("INSERT INTO orders(user_id,estado,total,direccion_entrega,comuna,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                            (uid, "pendiente_pago", total, perfil["direccion"], perfil["comuna"], now(), now()))
            oid = cur.lastrowid
            c.executemany("INSERT INTO order_items(order_id,product_id,nombre,precio_unit,cantidad) VALUES(?,?,?,?,?)",
                          [(oid, l["product_id"], l["nombre"], l["precio_unit"], l["cantidad"]) for l in lines])
            c.execute("INSERT INTO order_history(order_id,estado,actor,at) VALUES(?,?,?,?)", (oid, "pendiente_pago", uid, now()))
    except Exception:
        internal_call("POST", f"{INVENTORY}/internal/release", get_secret("INVENTORY_SERVICE_SECRET"), caller="orders",
                      json={"items": [{"product_id": l["product_id"], "cantidad": l["cantidad"]} for l in lines]})
        raise HTTPException(500, "No fue posible crear el pedido")
    publish_event({"evento": "pedido_creado", "id": oid, "total": total})
    return view_for(load(oid), ctx)


@app.get("/orders")
def my_orders(limite: int = Query(default=20, ge=1, le=50), offset: int = Query(default=0, ge=0), ctx: Ctx = Depends(guard)):
    uid = require_user(ctx)
    with read("orders") as c:
        ids = [r["id"] for r in c.execute("SELECT id FROM orders WHERE user_id=? ORDER BY id DESC LIMIT ? OFFSET ?", (uid, limite, offset))]
    return [view_for(load(i), ctx) for i in ids]


@app.get("/orders/{order_id}")
def get_order(order_id: int, ctx: Ctx = Depends(guard)):
    return view_for(visible_or_404(order_id, ctx), ctx)


@app.delete("/orders/{order_id}")
def cancel_order(order_id: int, ctx: Ctx = Depends(guard)):
    """Anulación lógica: el registro y su historial se conservan."""
    o = visible_or_404(order_id, ctx)
    if o["user_id"] != ctx.user_id and not ctx.is_admin:
        raise HTTPException(403, "No autorizado")
    if o["estado"] != "pendiente_pago" and not ctx.is_admin:
        raise HTTPException(409, "Solo se puede anular un pedido pendiente de pago")
    if "anulado" not in TRANSITIONS.get(o["estado"], {}):
        raise HTTPException(409, f"No se puede anular un pedido en estado {o['estado']}")
    with tx("orders") as c:
        set_state(c, order_id, "anulado", ctx.user_id)
    release_stock(o)  # recuperación de stock
    publish_event({"evento": "pedido_anulado", "id": order_id})
    return view_for(load(order_id), ctx)


@app.patch("/orders/{order_id}/status")
def change_status(order_id: int, body: StatusIn, ctx: Ctx = Depends(guard)):
    if not ctx.is_staff:
        raise HTTPException(403, "Se requiere rol administrador o repartidor")
    o = load(order_id)
    if not o:
        raise HTTPException(404, "Pedido no encontrado")
    allowed = TRANSITIONS.get(o["estado"], {}).get(body.estado)
    role = "admin" if ctx.is_admin else "delivery"
    if allowed is None:
        raise HTTPException(409, f"Transición {o['estado']} -> {body.estado} no permitida")
    if role not in allowed:
        raise HTTPException(403, "Su rol no puede realizar esta transición")
    with tx("orders") as c:
        set_state(c, order_id, body.estado, ctx.user_id)
    if body.estado == "anulado":
        release_stock(o)
    publish_event({"evento": "pedido_" + body.estado, "id": order_id})
    return view_for(load(order_id), ctx)


# ---- Contratos internos ----
@app.get("/internal/orders/{order_id}")
def internal_get(order_id: int, ctx: Ctx = Depends(guard)):
    only_callers(ctx, "payments", "graphql")
    o = load(order_id)
    if not o:
        raise HTTPException(404, "Pedido no encontrado")
    return o


@app.get("/internal/orders")
def internal_list(user_id: str, limite: int = Query(default=10, ge=1, le=20), offset: int = Query(default=0, ge=0),
                  ctx: Ctx = Depends(guard)):
    only_callers(ctx, "graphql")
    with read("orders") as c:
        ids = [r["id"] for r in c.execute("SELECT id FROM orders WHERE user_id=? ORDER BY id DESC LIMIT ? OFFSET ?", (user_id, limite, offset))]
    return [load(i) for i in ids]


@app.post("/internal/orders/{order_id}/mark-paid")
def mark_paid(order_id: int, ctx: Ctx = Depends(guard)):
    """Único camino hacia 'pagado': lo invoca payments tras validar al proveedor."""
    only_callers(ctx, "payments")
    o = load(order_id)
    if not o:
        raise HTTPException(404, "Pedido no encontrado")
    if o["estado"] == "pagado":
        return {"estado": "pagado", "idempotent": True}
    if o["estado"] != "pendiente_pago":
        raise HTTPException(409, f"Pedido en estado {o['estado']} no puede pasar a pagado")
    with tx("orders") as c:
        set_state(c, order_id, "pagado", "payments")
    publish_event({"evento": "pedido_pagado", "id": order_id})
    return {"estado": "pagado", "idempotent": False}
