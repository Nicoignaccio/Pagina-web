"""Auth Service (puerto 8100): registro, login, emisión/revocación de tokens e introspección."""
import hashlib
import hmac
import os
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from common.config import get_secret
from common.db import init, read, tx
from common.web import add_request_logging

DDL = """
CREATE TABLE IF NOT EXISTS users(
  id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL,
  pw_hash TEXT NOT NULL, salt TEXT NOT NULL, roles TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(
  token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, expires_at TEXT NOT NULL);
"""
TOKEN_LIFETIME_MINUTES = 15
PBKDF2_ITERATIONS = 600_000
DUMMY_SALT = os.urandom(16)

app = FastAPI(title="Authentication Service", description="Registro, login e introspección de tokens")
add_request_logging(app, "auth")


def hash_password(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS).hex()


def sha256(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@app.on_event("startup")
def startup():
    init("auth", DDL)
    seed = os.getenv("SEED_PASSWORD")
    with tx("auth") as c:
        if seed and c.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            for uid, uname, roles in [("usr-001", "cliente_fukusuke", "customer"),
                                      ("usr-004", "cliente_dos", "customer"),
                                      ("usr-002", "repartidor_maipu", "delivery"),
                                      ("usr-003", "admin_fukusuke", "customer,admin")]:
                salt = os.urandom(16)
                c.execute("INSERT INTO users VALUES(?,?,?,?,?)", (uid, uname, hash_password(seed, salt), salt.hex(), roles))


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_]+$")
    password: str = Field(min_length=8, max_length=64)


class TokenBody(BaseModel):
    token: str = Field(min_length=10, max_length=200)


def require_gateway(secret_header: str):
    if not secrets.compare_digest(secret_header.encode(), get_secret("AUTH_INTROSPECTION_SECRET").encode()):
        raise HTTPException(403, "Gateway no autorizado")


@app.get("/health")
def health():
    return {"status": "OK", "service": "Authentication service"}


@app.post("/register", status_code=201)
def register(body: Credentials, x_gateway_auth_secret: str = Header(default="")):
    require_gateway(x_gateway_auth_secret)
    uid, salt = f"usr-{uuid.uuid4().hex[:8]}", os.urandom(16)
    try:
        with tx("auth") as c:
            c.execute("INSERT INTO users VALUES(?,?,?,?,?)",
                      (uid, body.username, hash_password(body.password, salt), salt.hex(), "customer"))
    except Exception:
        raise HTTPException(409, "No fue posible registrar ese usuario")
    return {"user_id": uid, "username": body.username}


@app.post("/login")
def login(body: Credentials, x_gateway_auth_secret: str = Header(default="")):
    require_gateway(x_gateway_auth_secret)
    with read("auth") as c:
        user = c.execute("SELECT * FROM users WHERE username=?", (body.username,)).fetchone()
    salt = bytes.fromhex(user["salt"]) if user else DUMMY_SALT
    computed = hash_password(body.password, salt)  # se calcula siempre: tiempo similar con/sin usuario
    if not user or not hmac.compare_digest(computed, user["pw_hash"]):
        raise HTTPException(401, "Credenciales inválidas")
    token = secrets.token_urlsafe(32)
    exp = datetime.now(timezone.utc) + timedelta(minutes=TOKEN_LIFETIME_MINUTES)
    with tx("auth") as c:
        c.execute("INSERT INTO sessions VALUES(?,?,?)", (sha256(token), user["id"], exp.isoformat()))
    return {"access_token": token, "token_type": "bearer", "expires_in": TOKEN_LIFETIME_MINUTES * 60}


@app.post("/introspect")
def introspect(body: TokenBody, x_gateway_auth_secret: str = Header(default="")):
    require_gateway(x_gateway_auth_secret)
    with read("auth") as c:
        row = c.execute("SELECT s.user_id, s.expires_at, u.username, u.roles FROM sessions s "
                        "JOIN users u ON u.id=s.user_id WHERE s.token_hash=?", (sha256(body.token),)).fetchone()
    if not row or datetime.now(timezone.utc) > datetime.fromisoformat(row["expires_at"]):
        if row:
            with tx("auth") as c:
                c.execute("DELETE FROM sessions WHERE token_hash=?", (sha256(body.token),))
        return {"active": False}
    return {"active": True, "user_id": row["user_id"], "username": row["username"],
            "roles": row["roles"].split(","), "expires_at": row["expires_at"]}


@app.post("/logout")
def logout(body: TokenBody, x_gateway_auth_secret: str = Header(default="")):
    """Solo el gateway puede invocarlo y únicamente con el token del propio usuario autenticado."""
    require_gateway(x_gateway_auth_secret)
    with tx("auth") as c:
        c.execute("DELETE FROM sessions WHERE token_hash=?", (sha256(body.token),))
    return {"message": "Sesión finalizada"}
