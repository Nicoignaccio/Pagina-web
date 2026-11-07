"""Inicia todos los servicios en local. Genera secretos aleatorios en cada arranque (nada queda en el código).

Uso:  python scripts/run_all.py            -> secretos por variable de entorno (mínimo privilegio por proceso)
      python scripts/run_all.py --vault    -> los carga en Vault (VAULT_ADDR, VAULT_TOKEN) y los servicios los leen de allí
Los secretos y la clave de los usuarios de prueba se guardan en .run/secrets.env (ignorado por git) para las pruebas.
"""
import argparse
import os
import secrets
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
SERVICES = {  # nombre: (módulo, puerto)
    "auth": ("auth_service.main:app", 8100), "inventory": ("inventory.main:app", 9001),
    "clients": ("clients.main:app", 9002), "orders": ("orders.main:app", 9003),
    "payments": ("payments.main:app", 9004), "graphql": ("graphql_gateway.main:app", 9005),
    "gateway": ("gateway.main:app", 8000),
}
# Mínimo privilegio: cada proceso recibe solo los secretos que necesita.
NEEDS = {
    "auth": ["AUTH_INTROSPECTION_SECRET", "SEED_PASSWORD"],
    "inventory": ["INVENTORY_SERVICE_SECRET"],
    "clients": ["CLIENTS_SERVICE_SECRET"],
    "orders": ["ORDERS_SERVICE_SECRET", "INVENTORY_SERVICE_SECRET", "CLIENTS_SERVICE_SECRET"],
    "payments": ["PAYMENTS_SERVICE_SECRET", "ORDERS_SERVICE_SECRET", "PAYMENTS_WEBHOOK_SECRET"],
    "graphql": ["GRAPHQL_SERVICE_SECRET", "ORDERS_SERVICE_SECRET", "INVENTORY_SERVICE_SECRET", "PAYMENTS_SERVICE_SECRET"],
    "gateway": ["AUTH_INTROSPECTION_SECRET", "INVENTORY_SERVICE_SECRET", "CLIENTS_SERVICE_SECRET", "ORDERS_SERVICE_SECRET",
                "PAYMENTS_SERVICE_SECRET", "GRAPHQL_SERVICE_SECRET"],
}
ALL = sorted({s for v in NEEDS.values() for s in v})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", action="store_true")
    ap.add_argument("--data-dir", default=None)
    args = ap.parse_args()

    secrets_map = {name: secrets.token_urlsafe(24) for name in ALL}
    run_dir = ROOT / ".run"
    run_dir.mkdir(exist_ok=True)
    (run_dir / "secrets.env").write_text("".join(f"{k}={v}\n" for k, v in secrets_map.items()))
    data_dir = args.data_dir or tempfile.mkdtemp(prefix="fukusuke-data-")

    base_env = {**os.environ, "DATA_DIR": data_dir, "PYTHONPATH": str(ROOT), "CORS_ORIGINS": os.getenv("CORS_ORIGINS", "")}
    if args.vault:
        addr, token = os.getenv("VAULT_ADDR", "http://127.0.0.1:8200"), os.getenv("VAULT_TOKEN", "dev-only-token")
        r = httpx.post(f"{addr}/v1/secret/data/fukusuke", headers={"X-Vault-Token": token}, json={"data": secrets_map}, timeout=5)
        r.raise_for_status()
        print(f"Secretos cargados en Vault ({addr}, ruta secret/fukusuke)")
        base_env.update(VAULT_ADDR=addr, VAULT_TOKEN=token, SEED_PASSWORD=secrets_map["SEED_PASSWORD"])

    procs = []
    try:
        for name, (module, port) in SERVICES.items():
            env = dict(base_env)
            if not args.vault:
                env.update({k: secrets_map[k] for k in NEEDS[name]})
            procs.append(subprocess.Popen([sys.executable, "-m", "uvicorn", module, "--host", "127.0.0.1", "--port", str(port),
                                           "--log-level", "warning"], cwd=ROOT, env=env))
        for name, (_, port) in SERVICES.items():
            for _ in range(60):
                try:
                    if httpx.get(f"http://127.0.0.1:{port}/health", timeout=1).status_code == 200:
                        break
                except httpx.HTTPError:
                    time.sleep(0.5)
            else:
                raise SystemExit(f"El servicio {name} no respondió en :{port}")
        print("Sistema listo. Gateway público: http://127.0.0.1:8000  (Ctrl+C para detener)")
        print(f"Secretos de prueba en {run_dir / 'secrets.env'}")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            p.wait(timeout=10)


if __name__ == "__main__":
    main()
