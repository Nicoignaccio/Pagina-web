"""Genera .env (para docker compose) y .run/secrets.env (para las pruebas) con secretos aleatorios. No se versiona."""
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAMES = ["AUTH_INTROSPECTION_SECRET", "INVENTORY_SERVICE_SECRET", "CLIENTS_SERVICE_SECRET", "ORDERS_SERVICE_SECRET",
         "PAYMENTS_SERVICE_SECRET", "GRAPHQL_SERVICE_SECRET", "PAYMENTS_WEBHOOK_SECRET", "SEED_PASSWORD"]
vals = {n: secrets.token_urlsafe(24) for n in NAMES}
(ROOT / ".run").mkdir(exist_ok=True)
(ROOT / ".run" / "secrets.env").write_text("".join(f"{k}={v}\n" for k, v in vals.items()))
(ROOT / ".env").write_text("".join(f"{k}={v}\n" for k, v in vals.items()) +
                           f"VAULT_TOKEN={secrets.token_urlsafe(24)}\nCORS_ORIGINS=https://nicoignaccio.github.io\n")
print("Generados .env y .run/secrets.env (no los suba a git)")
