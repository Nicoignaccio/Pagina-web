"""Agregación GraphQL (orders + inventory + payments) con autorización por recurso y campo."""
import hashlib
import hmac
import json
import uuid

from conftest import SECRETS, auth

Q = """query($id:Int!){ resumenPedido(id:$id){ id estado total direccionEntrega pagoEstado detalleDegradado
        items{ nombre cantidad subtotal categoria descripcion disponibleAhora } } }"""


def gql(api, token, query, variables=None):
    return api.post("/graphql", headers=auth(token), json={"query": query, "variables": variables or {}})


def crear_pedido(api, token):
    return api.post("/orders", headers=auth(token), json={"items": [{"product_id": 1, "cantidad": 1}, {"product_id": 2, "cantidad": 2}]}).json()


def test_graphql_requiere_sesion(api):
    assert api.post("/graphql", json={"query": "{ misPedidos { id } }"}).status_code == 401


def test_agregacion_combina_tres_subsistemas(api, t_cliente):
    p = crear_pedido(api, t_cliente)
    d = gql(api, t_cliente, Q, {"id": p["id"]}).json()["data"]["resumenPedido"]
    assert d["total"] == 6500 + 2 * 7200
    assert {i["nombre"] for i in d["items"]} == {"Roll California", "Ramen Tonkotsu"}
    assert all(i["categoria"] and i["descripcion"] for i in d["items"])  # datos de inventory
    assert d["pagoEstado"] == "sin_pago" and d["detalleDegradado"] is False  # dato de payments


def test_graphql_no_filtra_pedidos_ajenos(api, t_cliente, t_cliente2):
    p = crear_pedido(api, t_cliente)
    assert gql(api, t_cliente2, Q, {"id": p["id"]}).json()["data"]["resumenPedido"] is None
    lista = gql(api, t_cliente2, "{ misPedidos(limite: 100){ id } }").json()["data"]["misPedidos"]
    assert p["id"] not in [o["id"] for o in lista]


def test_autorizacion_por_campo_repartidor_no_ve_pago(api, t_cliente, t_delivery, t_admin):
    p = crear_pedido(api, t_cliente)
    assert gql(api, t_delivery, Q, {"id": p["id"]}).json()["data"]["resumenPedido"]["pagoEstado"] is None
    assert gql(api, t_admin, Q, {"id": p["id"]}).json()["data"]["resumenPedido"]["pagoEstado"] == "sin_pago"


def test_limites_profundidad_alias_e_introspeccion(api, t_cliente):
    assert "errors" in gql(api, t_cliente, "{ __schema { types { name } } }").json()          # introspección deshabilitada
    alias = "{ " + " ".join(f"a{i}: misPedidos {{ id }}" for i in range(8)) + " }"
    assert "errors" in gql(api, t_cliente, alias).json()                                      # demasiados alias
    assert "errors" in gql(api, t_cliente, "{ misPedidos { id campoInexistente } }").json()   # campos fuera del schema
