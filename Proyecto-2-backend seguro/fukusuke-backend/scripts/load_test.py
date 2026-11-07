"""Prueba de carga reproducible (MEDICIÓN, no proyección) sobre el catálogo y la agregación GraphQL.

Requisitos: sistema iniciado con límites altos, p. ej.  RATE_LIMIT_API=1000000 python scripts/run_all.py
Uso:  python scripts/load_test.py --concurrencia 20 --duracion 15
Registra entorno, concurrencia, duración, p95, throughput, errores y CPU/memoria de los procesos uvicorn.
"""
import argparse
import asyncio
import platform
import statistics
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
BASE = "http://127.0.0.1:8000/api/v1"


async def worker(client, make_request, stop_at, lat, errs):
    while time.time() < stop_at:
        t0 = time.perf_counter()
        try:
            r = await make_request(client)
            ok = r.status_code == 200
        except httpx.HTTPError:
            ok = False
        lat.append((time.perf_counter() - t0) * 1000)
        if not ok:
            errs.append(1)


def cpu_mem():
    try:
        import psutil
        ps = [p for p in psutil.process_iter(["cmdline", "memory_info"]) if "uvicorn" in " ".join(p.info["cmdline"] or [])]
        for p in ps:
            p.cpu_percent(None)
        return ps
    except ImportError:
        return []


async def scenario(nombre, make_request, conc, dur):
    lat, errs = [], []
    procs = cpu_mem()
    async with httpx.AsyncClient(timeout=10, limits=httpx.Limits(max_connections=conc)) as client:
        t0 = time.time()
        await asyncio.gather(*[worker(client, make_request, t0 + dur, lat, errs) for _ in range(conc)])
        elapsed = time.time() - t0
    cpu = sum(p.cpu_percent(None) for p in procs) if procs else float("nan")
    mem = sum(p.memory_info().rss for p in procs) / 1e6 if procs else float("nan")
    lat.sort()
    p95 = lat[int(len(lat) * 0.95) - 1] if lat else float("nan")
    print(f"| {nombre} | {conc} | {dur}s | {len(lat)/elapsed:.1f} req/s | {statistics.median(lat):.1f} ms | {p95:.1f} ms | "
          f"{len(errs)} ({100*len(errs)/max(len(lat),1):.2f}%) | {cpu:.0f}% | {mem:.0f} MB |")


async def main(conc, dur):
    secrets = dict(l.split("=", 1) for l in (ROOT / ".run" / "secrets.env").read_text().splitlines() if "=" in l)
    async with httpx.AsyncClient(timeout=10) as c:
        tok = (await c.post(f"{BASE}/auth/login", json={"username": "cliente_fukusuke", "password": secrets["SEED_PASSWORD"]})).json()["access_token"]
        await c.put(f"{BASE}/clients/me", headers={"Authorization": f"Bearer {tok}"}, json={
            "run": "11111111-1", "nombre_completo": "Cliente Ficticio", "email": "c@example.com", "direccion": "Av. Siempre Viva 742", "comuna": "Maipú"})
        oid = (await c.post(f"{BASE}/orders", headers={"Authorization": f"Bearer {tok}"}, json={"items": [{"product_id": 1, "cantidad": 1}]})).json()["id"]
    h = {"Authorization": f"Bearer {tok}"}
    q = {"query": "query($id:Int!){resumenPedido(id:$id){id estado total items{nombre categoria}}}", "variables": {"id": oid}}
    print(f"Entorno: {platform.platform()} | Python {platform.python_version()} | CPUs lógicas: {__import__('os').cpu_count()}")
    print("| Escenario | Concurrencia | Duración | Throughput | Mediana | p95 | Errores | CPU (suma uvicorn) | RAM (suma uvicorn) |")
    print("|---|---|---|---|---|---|---|---|---|")
    await scenario("GET /products (anónimo)", lambda c: c.get(f"{BASE}/products"), conc, dur)
    await scenario("POST /graphql resumenPedido", lambda c: c.post(f"{BASE}/graphql", headers=h, json=q), conc, dur)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--concurrencia", type=int, default=20)
    ap.add_argument("--duracion", type=int, default=15)
    a = ap.parse_args()
    asyncio.run(main(a.concurrencia, a.duracion))
