"""Acceso a secretos: Vault (KV v2) si está configurado; si no, variables de entorno."""
import os

import httpx

_vault_cache: dict = {}


def get_secret(name: str) -> str:
    addr, token = os.getenv("VAULT_ADDR"), os.getenv("VAULT_TOKEN")
    if addr and token:
        if not _vault_cache:
            r = httpx.get(f"{addr}/v1/secret/data/fukusuke", headers={"X-Vault-Token": token}, timeout=5.0)
            r.raise_for_status()
            _vault_cache.update(r.json()["data"]["data"])
        if name in _vault_cache:
            return _vault_cache[name]
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Secreto '{name}' no configurado")
    return value


def service_url(name: str, default_port: int) -> str:
    return os.getenv(f"{name}_URL", f"http://127.0.0.1:{default_port}")
