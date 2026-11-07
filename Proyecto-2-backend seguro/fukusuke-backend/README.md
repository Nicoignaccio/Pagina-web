# Fukusuke Sushi-Delivery — Backend seguro (Evaluación 2)

Servicios FastAPI con persistencia SQLite (una base por servicio), API Gateway con lista blanca de rutas, Auth Service con
introspección, GraphQL Gateway privado, secretos en Vault (o variables de entorno en modo local) y pruebas de integración.

| Servicio | Puerto | Exposición | Responsabilidad |
|---|---|---|---|
| gateway | 8000 | **pública** | Lista blanca de rutas, identidad, roles, límites, CORS |
| auth | 8100 | privada | Registro, login (PBKDF2+sal), tokens de 15 min, introspección, logout |
| inventory | 9001 | privada | Catálogo, stock (autoridad única), reserva/liberación atómica |
| clients | 9002 | privada | Perfil y datos personales del cliente |
| orders | 9003 | privada | Pedidos, máquina de estados, historial, anulación lógica |
| payments | 9004 | privada | Inicio de pago y aviso del proveedor (firma HMAC, idempotencia) |
| graphql | 9005 | privada | Agregación `resumenPedido` (orders + inventory + payments) |

## Requisitos
Python 3.12+ (modo local) o Docker Desktop (modo contenedores). `pip install -r requirements.txt`.

## Iniciar y detener — modo local (sin Docker)
```powershell
pip install -r requirements.txt
python scripts/run_all.py          # genera secretos aleatorios, crea datos de prueba y levanta los 7 servicios
# Ctrl+C detiene todo
python -m pytest tests -q          # en otra terminal (usa .run/secrets.env generado al iniciar)
```
Con Vault de desarrollo (como en clase): `.\vault server -dev -dev-root-token-id="dev-only-token"` y luego
`$env:VAULT_ADDR="http://127.0.0.1:8200"; $env:VAULT_TOKEN="dev-only-token"; python scripts/run_all.py --vault`.

## Iniciar y detener — Docker (red pública/privada)
```powershell
python scripts/gen_env.py          # crea .env y .run/secrets.env con secretos aleatorios
docker compose up --build -d       # solo el gateway publica el puerto 8000; la red 'private' es interna
python -m pytest tests -q
docker compose down -v             # detener y borrar datos
```

## Datos de prueba (ficticios)
Se crean al iniciar: 6 productos y los usuarios `cliente_fukusuke`, `cliente_dos` (customer), `repartidor_maipu` (delivery) y
`admin_fukusuke` (admin). La clave de prueba es `SEED_PASSWORD` (aleatoria, en `.run/secrets.env`; no se versiona).
RUN de prueba válidos: `11111111-1`, `22222222-2`.

## Pruebas
`python -m pytest tests -q` — contratos, los 6 casos de validación del módulo 7, propiedad de recursos, roles, acceso directo,
máquina de estados, stock, pagos duplicados/alterados, GraphQL (agregación, autorización por campo, límites) y secretos.
Aparte: `RUN_RATELIMIT=1 python -m pytest tests/test_ratelimit.py` (bloquea los logins por 60 s).
Carga: iniciar con `RATE_LIMIT_API=1000000 RATE_LIMIT_AUTH=1000 python scripts/run_all.py` y ejecutar `python scripts/load_test.py`.

## Rutas públicas (gateway, prefijo `/api/v1`)
| ID | Verbo y ruta | Acceso | Destino |
|---|---|---|---|
| A01-A03 | POST `/auth/register`, `/auth/login`, `/auth/logout` | anónimo / anónimo / sesión | auth |
| S01-S02 | GET `/products`, `/products/{id}` | anónimo (campos públicos) | inventory |
| S03-S04 | POST `/products`, PUT `/products/{id}` | admin | inventory |
| S05-S06 | GET / PUT `/clients/me` | sesión (propio) | clients |
| S07 | GET `/clients` | admin (sin RUN ni dirección) | clients |
| S08-S11 | POST/GET `/orders`, GET/DELETE `/orders/{id}` | sesión; dueño o staff; DELETE = anulación lógica | orders |
| S12 | PATCH `/orders/{id}/status` | admin o repartidor según transición | orders |
| S13 | POST `/payments` | sesión (dueño del pedido) | payments |
| S14 | POST `/payments/webhook` | proveedor (firma HMAC verificada en payments) | payments |
| S15 | POST `/graphql` | sesión; autorización por recurso y campo | graphql |

Toda ruta o verbo fuera de esta lista responde 404. Los endpoints `/internal/*` no están publicados.

## Secretos (solo referencias; los valores nunca van al repositorio)
| Referencia | Tipo | Emisor | Consumidor | Finalidad |
|---|---|---|---|---|
| AUTH_INTROSPECTION_SECRET | secreto compartido | Vault | gateway → auth | Autorizar introspección, login, registro y logout |
| INVENTORY_SERVICE_SECRET | credencial de servicio | Vault | gateway, orders → inventory | Acceso a inventory |
| CLIENTS_SERVICE_SECRET | credencial de servicio | Vault | gateway, orders → clients | Acceso a clients |
| ORDERS_SERVICE_SECRET | credencial de servicio | Vault | gateway, payments, graphql → orders | Acceso a orders |
| PAYMENTS_SERVICE_SECRET | credencial de servicio | Vault | gateway, graphql → payments | Acceso a payments |
| GRAPHQL_SERVICE_SECRET | credencial de servicio | Vault | gateway → graphql | Acceso al GraphQL Gateway |
| PAYMENTS_WEBHOOK_SECRET | firma HMAC | Vault / proveedor | payments | Verificar avisos del proveedor |
| SEED_PASSWORD | clave de datos de prueba | generador local | auth | Solo usuarios ficticios de prueba |

Modo local sin `--vault`: cada proceso recibe únicamente los secretos de esta tabla que necesita. Con Vault de desarrollo todos
leen la misma ruta (`secret/fukusuke`); en producción se usarían políticas AppRole por servicio, rotación y TLS.

## Health checks y logs
Cada servicio expone `GET /health`. Los logs incluyen `rid` (identificador de correlación) y solo método, ruta y estado:
nunca cabeceras, cuerpos, tokens ni datos personales.

## Limitaciones declaradas
- TLS no está habilitado en esta demo (se terminaría en un proxy inverso en producción).
- Sesiones en SQLite del Auth Service y límite de solicitudes en memoria (un solo gateway).
- El proveedor de pagos es un adaptador de prueba: se simula con avisos firmados (ver `tests/test_seguridad.py`).
- Analítica y gRPC no se implementan: ver `docs/ADR-001-analitica-y-grpc.md`.
