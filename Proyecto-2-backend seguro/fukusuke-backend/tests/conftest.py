"""Pruebas de integración contra el sistema en ejecución (python scripts/run_all.py)."""
import os
from pathlib import Path

import httpx
import pytest

BASE = os.getenv("GATEWAY_URL", "http://127.0.0.1:8000") + "/api/v1"
ROOT = Path(__file__).resolve().parent.parent


def load_secrets() -> dict:
    f = ROOT / ".run" / "secrets.env"
    if not f.exists():
        pytest.exit("Falta .run/secrets.env: inicie el sistema con 'python scripts/run_all.py'", 2)
    return dict(l.split("=", 1) for l in f.read_text().splitlines() if "=" in l)


SECRETS = load_secrets()


def login(username: str) -> str:
    r = httpx.post(f"{BASE}/auth/login", json={"username": username, "password": SECRETS["SEED_PASSWORD"]}, timeout=10)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


PERFIL = {"nombre_completo": "Cliente Ficticio", "email": "cliente@example.com", "telefono": "+56911112222",
          "direccion": "Av. Siempre Viva 742", "comuna": "Maipú"}


@pytest.fixture(scope="session")
def api():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


@pytest.fixture(scope="session")
def t_cliente(api):
    t = login("cliente_fukusuke")
    assert api.put("/clients/me", headers=auth(t), json={**PERFIL, "run": "11111111-1"}).status_code == 200
    return t


@pytest.fixture(scope="session")
def t_cliente2(api):
    t = login("cliente_dos")
    assert api.put("/clients/me", headers=auth(t), json={**PERFIL, "run": "22222222-2", "nombre_completo": "Otra Persona"}).status_code == 200
    return t


@pytest.fixture(scope="session")
def t_admin():
    return login("admin_fukusuke")


@pytest.fixture(scope="session")
def t_delivery():
    return login("repartidor_maipu")
