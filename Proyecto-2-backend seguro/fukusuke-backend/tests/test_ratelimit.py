"""Límite de solicitudes. Se ejecuta aparte porque bloquea los logins por 60 s:  RUN_RATELIMIT=1 pytest tests/test_ratelimit.py"""
import os

import httpx
import pytest

from conftest import BASE


@pytest.mark.skipif(not os.getenv("RUN_RATELIMIT"), reason="se ejecuta aparte (RUN_RATELIMIT=1)")
def test_login_limitado_a_10_por_minuto():
    codes = [httpx.post(f"{BASE}/auth/login", json={"username": "nadie_nadie", "password": "claveclave1"}, timeout=10).status_code
             for _ in range(12)]
    assert 429 in codes and codes[:10].count(401) >= 1
