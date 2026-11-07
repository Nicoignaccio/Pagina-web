"""GraphQL Gateway privado (puerto 9005): agrega orders + inventory + payments sin tocar sus bases."""
import os
from typing import List, Optional

import httpx
import strawberry
from fastapi import Depends, FastAPI
from graphql.validation import NoSchemaIntrospectionCustomRule
from strawberry.extensions import AddValidationRules, MaxAliasesLimiter, QueryDepthLimiter
from strawberry.fastapi import GraphQLRouter
from strawberry.types import Info

from common.config import get_secret, service_url
from common.security import Ctx, make_guard
from common.web import add_request_logging

guard = make_guard("GRAPHQL_SERVICE_SECRET")
ORDERS, INVENTORY, PAYMENTS = service_url("ORDERS", 9003), service_url("INVENTORY", 9001), service_url("PAYMENTS", 9004)
MAX_PAGE = 20


async def call(base: str, path: str, secret: str, params=None):
    async with httpx.AsyncClient(timeout=3.0) as client:
        r = await client.get(f"{base}{path}", params=params, headers={"X-Service-Token": get_secret(secret), "X-Caller": "graphql"})
    r.raise_for_status()
    return r.json()


@strawberry.type
class ItemResumen:
    product_id: int
    nombre: str
    cantidad: int
    precio_unitario: int
    subtotal: int
    categoria: Optional[str] = None
    descripcion: Optional[str] = None
    disponible_ahora: Optional[bool] = None


@strawberry.type
class PedidoResumen:
    id: int
    estado: str
    total: int
    creado: str
    direccion_entrega: str
    comuna: str
    items: List[ItemResumen]
    pago_estado: Optional[str]  # solo visible para el dueño y administradores
    detalle_degradado: bool     # true si alguna dependencia no respondió (error parcial controlado)


async def enrich(orders: List[dict], ctx: Ctx, with_payment: bool) -> List[PedidoResumen]:
    ids = sorted({i["product_id"] for o in orders for i in o["items"]})
    catalogo, degradado = {}, False
    if ids:  # una sola llamada por lote a inventory, sin N+1
        try:
            catalogo = {p["id"]: p for p in await call(INVENTORY, "/internal/products", "INVENTORY_SERVICE_SECRET", {"ids": ",".join(map(str, ids))})}
        except Exception:
            degradado = True
    out = []
    for o in orders:
        pago, deg = None, degradado
        if with_payment:
            try:
                pago = (await call(PAYMENTS, f"/internal/payments/by-order/{o['id']}", "PAYMENTS_SERVICE_SECRET"))["estado"]
            except Exception:
                deg = True
        items = [ItemResumen(product_id=i["product_id"], nombre=i["nombre"], cantidad=i["cantidad"], precio_unitario=i["precio_unit"],
                             subtotal=i["precio_unit"] * i["cantidad"],
                             categoria=catalogo.get(i["product_id"], {}).get("categoria"),
                             descripcion=catalogo.get(i["product_id"], {}).get("descripcion"),
                             disponible_ahora=catalogo.get(i["product_id"], {}).get("disponible")) for i in o["items"]]
        out.append(PedidoResumen(id=o["id"], estado=o["estado"], total=o["total"], creado=o["created_at"],
                                 direccion_entrega=o["direccion_entrega"], comuna=o["comuna"], items=items,
                                 pago_estado=pago, detalle_degradado=deg))
    return out


@strawberry.type
class Query:
    @strawberry.field
    async def resumen_pedido(self, info: Info, id: int) -> Optional[PedidoResumen]:
        ctx: Ctx = info.context["ctx"]
        try:
            o = await call(ORDERS, f"/internal/orders/{id}", "ORDERS_SERVICE_SECRET")
        except httpx.HTTPStatusError:
            return None
        if not (o["user_id"] == ctx.user_id or ctx.is_staff):
            return None  # mismo resultado que "no existe": no filtra pedidos ajenos
        puede_ver_pago = o["user_id"] == ctx.user_id or ctx.is_admin  # autorización por campo
        return (await enrich([o], ctx, puede_ver_pago))[0]

    @strawberry.field
    async def mis_pedidos(self, info: Info, limite: int = 10, offset: int = 0) -> List[PedidoResumen]:
        ctx: Ctx = info.context["ctx"]
        limite, offset = max(1, min(limite, MAX_PAGE)), max(0, offset)
        orders = await call(ORDERS, "/internal/orders", "ORDERS_SERVICE_SECRET",
                            {"user_id": ctx.user_id, "limite": limite, "offset": offset})
        return await enrich(orders, ctx, False)


rules = [QueryDepthLimiter(max_depth=5), MaxAliasesLimiter(max_alias_count=5)]
if os.getenv("GRAPHQL_INTROSPECTION", "false").lower() != "true":
    rules.append(AddValidationRules([NoSchemaIntrospectionCustomRule]))
schema = strawberry.Schema(query=Query, extensions=rules)


async def get_context(ctx: Ctx = Depends(guard)):
    return {"ctx": ctx}


app = FastAPI(title="graphql-gateway", description="Agregaciones GraphQL (privado)")
add_request_logging(app, "graphql")


@app.get("/health")
def health():
    return {"status": "OK", "service": "graphql-gateway"}


app.include_router(GraphQLRouter(schema, context_getter=get_context, graphql_ide=None), prefix="/graphql")
