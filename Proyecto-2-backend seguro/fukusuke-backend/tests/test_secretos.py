"""get_secret: prioriza Vault (KV v2) y cae a variables de entorno."""
import httpx

from common import config


def test_get_secret_desde_vault(monkeypatch):
    llamadas = []

    def fake_get(url, headers=None, timeout=None):
        llamadas.append((url, headers["X-Vault-Token"]))
        return httpx.Response(200, json={"data": {"data": {"ORDERS_SERVICE_SECRET": "desde-vault"}}}, request=httpx.Request("GET", url))

    monkeypatch.setattr(config.httpx, "get", fake_get)
    monkeypatch.setattr(config, "_vault_cache", {})
    monkeypatch.setenv("VAULT_ADDR", "http://vault:8200")
    monkeypatch.setenv("VAULT_TOKEN", "t")
    monkeypatch.setenv("ORDERS_SERVICE_SECRET", "desde-env")
    assert config.get_secret("ORDERS_SERVICE_SECRET") == "desde-vault"
    assert llamadas == [("http://vault:8200/v1/secret/data/fukusuke", "t")]
    config.get_secret("ORDERS_SERVICE_SECRET")
    assert len(llamadas) == 1  # cacheado


def test_get_secret_desde_entorno_y_error_si_falta(monkeypatch):
    monkeypatch.delenv("VAULT_ADDR", raising=False)
    monkeypatch.setenv("X_SECRET", "v")
    assert config.get_secret("X_SECRET") == "v"
    monkeypatch.delenv("X_SECRET")
    try:
        config.get_secret("X_SECRET")
        assert False
    except RuntimeError:
        pass
