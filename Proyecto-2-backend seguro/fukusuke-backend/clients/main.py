"""clients (puerto 9002): perfil del cliente. Custodia datos personales restringidos."""
import re
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator

from common.db import init, read, tx
from common.security import Ctx, make_guard, only_callers, require_user
from common.web import add_request_logging

DDL = """
CREATE TABLE IF NOT EXISTS clients(
  user_id TEXT PRIMARY KEY, run TEXT NOT NULL, nombre_completo TEXT NOT NULL, email TEXT NOT NULL,
  telefono TEXT, direccion TEXT NOT NULL, comuna TEXT NOT NULL, updated_at TEXT NOT NULL);
"""
guard = make_guard("CLIENTS_SERVICE_SECRET")
app = FastAPI(title="clients", description="Perfil de clientes (privado)")
add_request_logging(app, "clients")


@app.on_event("startup")
def startup():
    init("clients", DDL)


def run_valido(run: str) -> bool:
    m = re.fullmatch(r"(\d{7,8})-([\dkK])", run.replace(".", ""))
    if not m:
        return False
    total, mult = 0, 2
    for d in reversed(m.group(1)):
        total += int(d) * mult
        mult = 2 if mult == 7 else mult + 1
    dv = 11 - total % 11
    esperado = "0" if dv == 11 else "K" if dv == 10 else str(dv)
    return m.group(2).upper() == esperado


class ProfileIn(BaseModel):
    run: str = Field(max_length=12)
    nombre_completo: str = Field(min_length=3, max_length=100)
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=120)
    telefono: Optional[str] = Field(default=None, pattern=r"^\+?\d{8,12}$")
    direccion: str = Field(min_length=5, max_length=160)
    comuna: str = Field(min_length=2, max_length=60)

    @field_validator("run")
    @classmethod
    def _run(cls, v):
        if not run_valido(v):
            raise ValueError("RUN inválido")
        return v.replace(".", "")


@app.get("/health")
def health():
    return {"status": "OK", "service": "clients"}


@app.get("/clients/me")
def my_profile(ctx: Ctx = Depends(guard)):
    uid = require_user(ctx)
    with read("clients") as c:
        r = c.execute("SELECT * FROM clients WHERE user_id=?", (uid,)).fetchone()
    if not r:
        raise HTTPException(404, "Perfil no registrado")
    return {k: r[k] for k in r.keys()}


@app.put("/clients/me")
def upsert_profile(p: ProfileIn, ctx: Ctx = Depends(guard)):
    uid = require_user(ctx)  # el user_id sale de la identidad verificada, nunca del cuerpo
    now = datetime.now(timezone.utc).isoformat()
    with tx("clients") as c:
        c.execute("INSERT INTO clients VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET "
                  "run=excluded.run, nombre_completo=excluded.nombre_completo, email=excluded.email, "
                  "telefono=excluded.telefono, direccion=excluded.direccion, comuna=excluded.comuna, updated_at=excluded.updated_at",
                  (uid, p.run, p.nombre_completo, p.email, p.telefono, p.direccion, p.comuna, now))
    return my_profile(ctx)


@app.get("/clients")
def list_clients(ctx: Ctx = Depends(guard)):
    if not ctx.is_admin:
        raise HTTPException(403, "Se requiere rol administrador")
    with read("clients") as c:  # minimización: el listado admin no incluye RUN ni dirección
        rows = c.execute("SELECT user_id, nombre_completo, email, comuna FROM clients ORDER BY nombre_completo").fetchall()
    return [dict(r) for r in rows]


@app.get("/internal/clients/{user_id}")
def delivery_snapshot(user_id: str, ctx: Ctx = Depends(guard)):
    only_callers(ctx, "orders")
    with read("clients") as c:
        r = c.execute("SELECT nombre_completo, direccion, comuna FROM clients WHERE user_id=?", (user_id,)).fetchone()
    if not r:
        raise HTTPException(404, "Perfil no registrado")
    return dict(r)
