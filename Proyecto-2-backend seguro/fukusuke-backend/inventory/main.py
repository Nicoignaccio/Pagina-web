"""inventory (puerto 9001): catálogo, disponibilidad y stock. Autoridad única sobre el stock."""
from typing import List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from common.db import init, read, tx
from common.security import Ctx, make_guard, only_callers
from common.web import add_request_logging

DDL = """
CREATE TABLE IF NOT EXISTS products(
  id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT NOT NULL, categoria TEXT NOT NULL,
  descripcion TEXT NOT NULL DEFAULT '', precio INTEGER NOT NULL CHECK(precio>0),
  stock INTEGER NOT NULL CHECK(stock>=0), disponible INTEGER NOT NULL DEFAULT 1);
"""
SEED = [("Roll California", "Sushi", "Roll de 10 piezas con palta, kanikama y pepino", 6500, 40),
        ("Ramen Tonkotsu", "Sopas", "Caldo de cerdo, fideos, huevo y cebollín", 7200, 25),
        ("Handroll Pollo Teriyaki", "Sushi", "Handroll de pollo teriyaki con queso crema", 4800, 30),
        ("Tabla Fukusuke", "Tablas", "Tabla de 30 piezas surtidas", 24900, 10),
        ("Gyozas de cerdo", "Entradas", "6 gyozas con salsa ponzu", 4200, 35),
        ("Té verde frío", "Bebidas", "Botella 500 ml", 1800, 60)]

guard = make_guard("INVENTORY_SERVICE_SECRET")
app = FastAPI(title="inventory", description="Catálogo y stock (privado)")
add_request_logging(app, "inventory")


@app.on_event("startup")
def startup():
    init("inventory", DDL)
    with tx("inventory") as c:
        if c.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0:
            c.executemany("INSERT INTO products(nombre,categoria,descripcion,precio,stock) VALUES(?,?,?,?,?)", SEED)


class ProductIn(BaseModel):
    nombre: str = Field(min_length=1, max_length=80)
    categoria: str = Field(min_length=1, max_length=40)
    descripcion: str = Field(default="", max_length=300)
    precio: int = Field(gt=0, le=1_000_000)
    stock: int = Field(ge=0, le=10_000)
    disponible: bool = True


class Line(BaseModel):
    product_id: int
    cantidad: int = Field(ge=1, le=20)


class Lines(BaseModel):
    items: List[Line] = Field(min_length=1, max_length=20)


def public(row, admin: bool) -> dict:
    d = {"id": row["id"], "nombre": row["nombre"], "categoria": row["categoria"],
         "descripcion": row["descripcion"], "precio": row["precio"], "disponible": bool(row["disponible"])}
    if admin:
        d["stock"] = row["stock"]  # el stock exacto es dato operativo, no público
    return d


@app.get("/health")
def health():
    return {"status": "OK", "service": "inventory"}


@app.get("/products")
def list_products(available: Optional[str] = Query(default=None), ctx: Ctx = Depends(guard)):
    if available not in (None, "true", "false"):
        raise HTTPException(400, "Filtro 'available' inválido (true|false)")
    sql, args = "SELECT * FROM products", []
    if available is not None:
        sql += " WHERE disponible=?"
        args.append(1 if available == "true" else 0)
    with read("inventory") as c:
        rows = c.execute(sql + " ORDER BY id", args).fetchall()
    return [public(r, ctx.is_admin) for r in rows]


@app.get("/products/{pid}")
def get_product(pid: int, ctx: Ctx = Depends(guard)):
    with read("inventory") as c:
        r = c.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
    if not r:
        raise HTTPException(404, "Producto no encontrado")
    return public(r, ctx.is_admin)


@app.post("/products", status_code=201)
def create_product(p: ProductIn, ctx: Ctx = Depends(guard)):
    if not ctx.is_admin:
        raise HTTPException(403, "Se requiere rol administrador")
    with tx("inventory") as c:
        cur = c.execute("INSERT INTO products(nombre,categoria,descripcion,precio,stock,disponible) VALUES(?,?,?,?,?,?)",
                        (p.nombre, p.categoria, p.descripcion, p.precio, p.stock, int(p.disponible)))
        pid = cur.lastrowid
    return get_product(pid, ctx)


@app.put("/products/{pid}")
def replace_product(pid: int, p: ProductIn, ctx: Ctx = Depends(guard)):
    if not ctx.is_admin:
        raise HTTPException(403, "Se requiere rol administrador")
    with tx("inventory") as c:
        cur = c.execute("UPDATE products SET nombre=?,categoria=?,descripcion=?,precio=?,stock=?,disponible=? WHERE id=?",
                        (p.nombre, p.categoria, p.descripcion, p.precio, p.stock, int(p.disponible), pid))
        if cur.rowcount == 0:
            raise HTTPException(404, "Producto no encontrado")
    return get_product(pid, ctx)


# ---- Contratos internos (nunca expuestos por el gateway) ----
@app.post("/internal/reserve")
def reserve(body: Lines, ctx: Ctx = Depends(guard)):
    """Descuenta stock de forma atómica y devuelve precios/nombres autoritativos."""
    only_callers(ctx, "orders")
    wanted: dict = {}
    for ln in body.items:
        wanted[ln.product_id] = wanted.get(ln.product_id, 0) + ln.cantidad
    result = []
    with tx("inventory") as c:  # rollback total si algún ítem falla
        for pid, qty in wanted.items():
            r = c.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
            if not r or not r["disponible"]:
                raise HTTPException(409, f"Producto {pid} no disponible")
            if r["stock"] < qty:
                raise HTTPException(409, f"Stock insuficiente para '{r['nombre']}'")
            c.execute("UPDATE products SET stock=stock-? WHERE id=?", (qty, pid))
            result.append({"product_id": pid, "nombre": r["nombre"], "precio_unit": r["precio"], "cantidad": qty})
    return {"items": result}


@app.post("/internal/release")
def release(body: Lines, ctx: Ctx = Depends(guard)):
    only_callers(ctx, "orders")
    with tx("inventory") as c:
        for ln in body.items:
            c.execute("UPDATE products SET stock=stock+? WHERE id=?", (ln.cantidad, ln.product_id))
    return {"released": True}


@app.get("/internal/products")
def batch_products(ids: str = Query(max_length=200), ctx: Ctx = Depends(guard)):
    """Lectura por lote (evita N llamadas desde la agregación GraphQL)."""
    only_callers(ctx, "graphql")
    try:
        wanted = [int(i) for i in ids.split(",") if i][:50]
    except ValueError:
        raise HTTPException(400, "ids inválidos")
    with read("inventory") as c:
        rows = c.execute(f"SELECT * FROM products WHERE id IN ({','.join('?' * len(wanted))})", wanted).fetchall() if wanted else []
    return [public(r, False) for r in rows]
