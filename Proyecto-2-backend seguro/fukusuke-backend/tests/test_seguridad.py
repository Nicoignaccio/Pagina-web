"""Los 6 casos de validación del Módulo 7 + reglas de autorización, estados, stock y pagos."""
import hashlib
import hmac
import json
import uuid

import httpx
import pytest

from conftest import SECRETS, auth

DIRECT = {"inventory": 9001, "clients": 9002, "orders": 9003, "payments": 9004, "graphql": 9005}


def pedido(api, token, items=None):
    r = api.post("/orders", headers=auth(token), json={"items": items or [{"product_id": 1, "cantidad": 1}]})
    assert r.status_code == 201, r.text
    return r.json()


def stock(api, t_admin, pid):
    return next(p["stock"] for p in api.get("/products", headers=auth(t_admin)).json() if p["id"] == pid)


def firmar(body: dict) -> tuple:
    raw = json.dumps(body).encode()
    return raw, hmac.new(SECRETS["PAYMENTS_WEBHOOK_SECRET"].encode(), raw, hashlib.sha256).hexdigest()


# ---------- Caso 1: acceso anónimo al catálogo ----------
def test_catalogo_anonimo_solo_campos_publicos(api):
    r = api.get("/products", params={"available": "true"})
    assert r.status_code == 200 and len(r.json()) > 0
    assert all("stock" not in p for p in r.json())


def test_filtro_invalido_400(api):
    assert api.get("/products", params={"available": "quizas"}).status_code == 400


# ---------- Caso 2: operación protegida sin sesión válida ----------
def test_pedido_sin_sesion_401(api):
    assert api.post("/orders", json={"items": [{"product_id": 1, "cantidad": 1}]}).status_code == 401
    assert api.post("/orders", headers=auth("token-falso-123456"), json={"items": []}).status_code == 401


# ---------- Caso 3: administración desde rol sin permiso ----------
def test_cliente_no_administra_catalogo(api, t_cliente):
    body = {"nombre": "X", "categoria": "Y", "precio": 1000, "stock": 1}
    assert api.post("/products", headers=auth(t_cliente), json=body).status_code == 403
    assert api.put("/products/1", headers=auth(t_cliente), json=body).status_code == 403
    assert api.get("/clients", headers=auth(t_cliente)).status_code == 403


def test_admin_crea_producto_y_ve_stock(api, t_admin):
    body = {"nombre": "Producto de prueba", "categoria": "Pruebas", "precio": 1500, "stock": 5}
    r = api.post("/products", headers=auth(t_admin), json=body)
    assert r.status_code == 201 and r.json()["stock"] == 5


def test_cabeceras_de_identidad_del_navegador_se_ignoran(api, t_cliente):
    """Un cliente que inyecta X-User-Roles: admin no obtiene privilegios."""
    r = api.post("/products", headers={**auth(t_cliente), "X-User-Roles": "admin", "X-User-Id": "usr-003"},
                 json={"nombre": "X", "categoria": "Y", "precio": 1000, "stock": 1})
    assert r.status_code == 403


# ---------- Caso 4: consulta de un pedido ajeno ----------
def test_pedido_ajeno_denegado(api, t_cliente, t_cliente2):
    p = pedido(api, t_cliente)
    assert api.get(f"/orders/{p['id']}", headers=auth(t_cliente)).status_code == 200
    r = api.get(f"/orders/{p['id']}", headers=auth(t_cliente2))
    assert r.status_code == 404 and "Cliente Ficticio" not in r.text and "Siempre Viva" not in r.text
    assert api.delete(f"/orders/{p['id']}", headers=auth(t_cliente2)).status_code == 404
    assert p["id"] not in [o["id"] for o in api.get("/orders", headers=auth(t_cliente2)).json()]


# ---------- Caso 5: acceso directo al backend sin identidad autorizada ----------
def test_acceso_directo_a_servicios_privados_rechazado():
    """Local: el servicio responde 403/404. En Docker: el puerto ni siquiera es alcanzable (red privada)."""
    for name, port in DIRECT.items():
        try:
            r = httpx.get(f"http://127.0.0.1:{port}/orders" if name == "orders" else f"http://127.0.0.1:{port}/products", timeout=5)
        except httpx.ConnectError:
            continue
        assert r.status_code in (403, 404), f"{name}: {r.status_code}"
    try:
        r = httpx.get("http://127.0.0.1:9003/orders", headers={"X-Service-Token": "adivinado", "X-User-Id": "usr-001"}, timeout=5)
        assert r.status_code == 403
    except httpx.ConnectError:
        pass


def test_rutas_internas_no_estan_publicadas(api, t_admin):
    for ruta in ["/internal/orders/1", "/internal/reserve", "/internal/clients/usr-001", "/orders/1/mark-paid"]:
        assert api.get(ruta, headers=auth(t_admin)).status_code == 404
    assert api.post("/internal/reserve", headers=auth(t_admin), json={}).status_code == 404


def test_servicio_interno_rechaza_llamador_no_autorizado():
    """Aun con un secreto válido, inventory solo acepta /internal/* de 'orders' (solo ejecutable en modo local)."""
    h = {"X-Service-Token": SECRETS["INVENTORY_SERVICE_SECRET"], "X-Caller": "payments"}
    try:
        r = httpx.post("http://127.0.0.1:9001/internal/reserve", headers=h, json={"items": [{"product_id": 1, "cantidad": 1}]}, timeout=5)
    except httpx.ConnectError:
        pytest.skip("puerto privado no alcanzable desde el host (modo Docker)")
    assert r.status_code == 403


# ---------- Caso 6: confirmar pago con datos alterados del frontend ----------
def test_frontend_no_puede_fijar_total_ni_estado(api, t_cliente):
    r = api.post("/orders", headers=auth(t_cliente), json={"items": [{"product_id": 1, "cantidad": 2}],
                                                           "total": 1, "estado": "pagado", "precio": 1})
    assert r.status_code == 201
    assert r.json()["estado"] == "pendiente_pago" and r.json()["total"] == 13000


def test_pago_con_datos_alterados_y_webhook(api, t_cliente):
    p = pedido(api, t_cliente)
    pay = api.post("/payments", headers=auth(t_cliente), json={"order_id": p["id"], "monto": 1, "estado": "aprobado"}).json()
    assert pay["monto"] == p["total"]  # el monto sale de orders, no del navegador
    ev = {"event_id": uuid.uuid4().hex, "provider_ref": pay["provider_ref"], "status": "approved", "amount": p["total"]}
    raw, sig = firmar(ev)
    # sin firma / firma falsa
    assert api.post("/payments/webhook", content=raw, headers={"Content-Type": "application/json"}).status_code == 401
    assert api.post("/payments/webhook", content=raw, headers={"Content-Type": "application/json", "X-Provider-Signature": "00" * 32}).status_code == 401
    assert api.get(f"/orders/{p['id']}", headers=auth(t_cliente)).json()["estado"] == "pendiente_pago"
    # firma válida pero monto alterado
    raw_bad, sig_bad = firmar({**ev, "event_id": uuid.uuid4().hex, "amount": 1})
    assert api.post("/payments/webhook", content=raw_bad, headers={"Content-Type": "application/json", "X-Provider-Signature": sig_bad}).status_code == 409
    # aviso legítimo
    ok = api.post("/payments/webhook", content=raw, headers={"Content-Type": "application/json", "X-Provider-Signature": sig})
    assert ok.status_code == 200 and ok.json()["estado"] == "aprobado"
    assert api.get(f"/orders/{p['id']}", headers=auth(t_cliente)).json()["estado"] == "pagado"
    # mismo aviso reenviado: no se procesa dos veces
    dup = api.post("/payments/webhook", content=raw, headers={"Content-Type": "application/json", "X-Provider-Signature": sig})
    assert dup.status_code == 200 and dup.json()["duplicate"] is True


def test_no_se_paga_pedido_ajeno(api, t_cliente, t_cliente2):
    p = pedido(api, t_cliente)
    assert api.post("/payments", headers=auth(t_cliente2), json={"order_id": p["id"]}).status_code == 404


# ---------- Reglas de negocio: stock, estados, anulación ----------
def test_anulacion_recupera_stock_y_conserva_historial(api, t_cliente, t_admin):
    antes = stock(api, t_admin, 3)
    p = pedido(api, t_cliente, [{"product_id": 3, "cantidad": 3}])
    assert stock(api, t_admin, 3) == antes - 3
    r = api.delete(f"/orders/{p['id']}", headers=auth(t_cliente))
    assert r.status_code == 200 and r.json()["estado"] == "anulado"
    assert stock(api, t_admin, 3) == antes
    assert api.get(f"/orders/{p['id']}", headers=auth(t_cliente)).status_code == 200  # el registro se conserva


def test_stock_insuficiente_no_altera_inventario(api, t_cliente, t_admin):
    antes = stock(api, t_admin, 4)
    r = api.post("/orders", headers=auth(t_cliente), json={"items": [{"product_id": 4, "cantidad": 1}, {"product_id": 4, "cantidad": 20},
                                                                       {"product_id": 1, "cantidad": 1}]})
    assert r.status_code == 409
    assert stock(api, t_admin, 4) == antes


def test_validaciones_de_entrada(api, t_cliente):
    assert api.post("/orders", headers=auth(t_cliente), json={"items": []}).status_code == 422
    assert api.post("/orders", headers=auth(t_cliente), json={"items": [{"product_id": 1, "cantidad": 0}]}).status_code == 422
    assert api.post("/orders", headers=auth(t_cliente), json={"items": [{"product_id": 999, "cantidad": 1}]}).status_code == 409


def test_maquina_de_estados_y_roles(api, t_cliente, t_admin, t_delivery):
    p = pedido(api, t_cliente)
    st = lambda tok, estado: api.patch(f"/orders/{p['id']}/status", headers=auth(tok), json={"estado": estado})
    assert st(t_cliente, "pagado").status_code == 403           # el cliente no cambia estados
    assert st(t_admin, "entregado").status_code == 409          # transición inválida
    pay = api.post("/payments", headers=auth(t_cliente), json={"order_id": p["id"]}).json()
    raw, sig = firmar({"event_id": uuid.uuid4().hex, "provider_ref": pay["provider_ref"], "status": "approved", "amount": p["total"]})
    api.post("/payments/webhook", content=raw, headers={"Content-Type": "application/json", "X-Provider-Signature": sig})
    assert st(t_delivery, "en_preparacion").status_code == 403  # repartidor no prepara
    assert st(t_admin, "en_preparacion").status_code == 200
    assert st(t_admin, "despachado").status_code == 200
    assert st(t_delivery, "entregado").status_code == 200


def test_perfil_valida_run_y_no_acepta_user_id_del_cuerpo(api, t_cliente):
    malo = {"nombre_completo": "Cliente Ficticio", "email": "c@example.com", "direccion": "Calle 12345", "comuna": "Maipú", "run": "12345678-9"}
    assert api.put("/clients/me", headers=auth(t_cliente), json=malo).status_code == 422
    perfil = api.get("/clients/me", headers=auth(t_cliente)).json()
    assert perfil["run"] == "11111111-1"


# ---------- Sesiones ----------
def test_logout_revoca_token(api):
    r = api.post("/auth/login", json={"username": "cliente_dos", "password": SECRETS["SEED_PASSWORD"]})
    t = r.json()["access_token"]
    assert api.get("/clients/me", headers=auth(t)).status_code in (200, 404)
    assert api.post("/auth/logout", headers=auth(t)).status_code == 200
    assert api.get("/clients/me", headers=auth(t)).status_code == 401
    assert api.post("/auth/logout").status_code == 401  # sin sesión no se puede invocar


def test_login_no_revela_si_el_usuario_existe(api):
    a = api.post("/auth/login", json={"username": "no_existe_nadie", "password": "claveclave1"})
    b = api.post("/auth/login", json={"username": "cliente_dos", "password": "claveclave1"})
    assert a.status_code == b.status_code == 401 and a.json() == b.json()


def test_ruta_o_verbo_fuera_de_lista_blanca(api, t_admin):
    assert api.delete("/products/1", headers=auth(t_admin)).status_code == 404   # no existe DELETE de productos
    assert api.get("/loquesea").status_code == 404
