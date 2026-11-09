# Fukusuke Sushi-Delivery — Backend seguro (Evaluación 2, Caso 19)

Backend de microservicios para la venta y despacho de sushi. Cada servicio es una API FastAPI con su propia base SQLite;
el único punto de entrada público es un API Gateway con lista blanca de rutas. Incluye autenticación con introspección,
control de roles y propiedad, un GraphQL Gateway privado, gestión de secretos (Vault o variables de entorno) y una suite de
pruebas de integración.

- **Autor:** Nicolás Ignacio Garrido Maldonado — Universidad Andrés Bello
- **Asignatura:** Desarrollo web y movil 
- **Informe asociado:** `Informe_Arquitectura_Evaluacion_2_Caso19.docx` (10 módulos)

---

## 1. Arquitectura

```
Navegador / Frontend ──HTTP(S)──► API Gateway :8000  (único puerto público)
Proveedor de pagos  ──webhook───►        │
                                         │  red privada (docker: internal)
        ┌────────────┬───────────┬───────┴────┬────────────┬─────────────┐
        ▼            ▼           ▼            ▼            ▼             ▼
     auth :8100  inventory   clients      orders       payments      graphql
                  :9001       :9002        :9003        :9004         :9005
                     ▲           ▲            │ │           │             │
                     └───────────┴────────────┘ └──► ActiveMQ (opcional)  │
                     (orders reserva stock y lee perfil)                    │
                     payments ──► orders (marca pagado)                     │
                     graphql ──► orders + inventory + payments (solo lectura)
```

| Servicio | Puerto | Exposición | Responsabilidad |
|---|---|---|---|
| gateway | 8000 | **pública** | Lista blanca de rutas, identidad, roles, límites de solicitudes, CORS, tamaño de cuerpo |
| auth | 8100 | privada | Registro, login (PBKDF2 + sal), tokens de 15 min, introspección, logout |
| inventory | 9001 | privada | Catálogo y stock (autoridad única), reserva y liberación atómica |
| clients | 9002 | privada | Perfil y datos personales del cliente (RUN, dirección, teléfono) |
| orders | 9003 | privada | Pedidos, máquina de estados, historial, anulación lógica |
| payments | 9004 | privada | Inicio de pago y aviso del proveedor (firma HMAC, idempotencia) |
| graphql | 9005 | privada | Agregación `resumenPedido` y `misPedidos` (orders + inventory + payments) |

### Máquina de estados del pedido

`pendiente_pago → pagado → en_preparacion → despachado → entregado`; en cualquier estado anterior a `despachado` puede
pasar a `anulado`.

| Estado actual | Nuevo estado | Quién puede |
|---|---|---|
| pendiente_pago | anulado | Dueño o admin |
| pendiente_pago | pagado | Solo `payments`, al aprobarse el pago (llamada interna) |
| pagado | en_preparacion / anulado | Admin |
| en_preparacion | despachado / anulado | Admin |
| despachado | entregado | Admin o repartidor |

---

## 2. Requisitos

- **Python 3.12 o superior** (modo local) o **Docker Desktop** (modo contenedores).
- Windows PowerShell, Linux o macOS. Los comandos de abajo usan PowerShell; en Linux/macOS cambia
  `$env:VARIABLE="valor"; comando` por `VARIABLE=valor comando`.
- Opcional: `pip install psutil` para que la prueba de carga registre CPU y memoria de los procesos.

Dependencias (`requirements.txt`): fastapi, uvicorn, httpx, pydantic, strawberry-graphql, stomp.py, pytest.

---

## 3. Inicio rápido — modo local (sin Docker)

```powershell
# 1. Instalar dependencias (una sola vez)
pip install -r requirements.txt

# 2. Terminal A: iniciar los 7 servicios
python scripts/run_all.py
#    Espera el mensaje:  Sistema listo. Gateway público: http://127.0.0.1:8000

# 3. Terminal B: ejecutar las pruebas
python -m pytest tests -q

# 4. Detener: Ctrl+C en la terminal A
```

`run_all.py` genera secretos aleatorios en cada arranque, los guarda en `.run/secrets.env` (ignorado por git), crea las bases
SQLite en una carpeta temporal y carga los datos de prueba. Todas las rutas del sistema se prueban a través del gateway.

### Con Vault de desarrollo (como en clase)

```powershell
.\vault server -dev -dev-root-token-id="dev-only-token"      # terminal aparte
$env:VAULT_ADDR="http://127.0.0.1:8200"; $env:VAULT_TOKEN="dev-only-token"
python scripts/run_all.py --vault
```

---

## 4. Inicio con Docker (red pública / privada)

```powershell
python scripts/gen_env.py          # crea .env y .run/secrets.env con secretos aleatorios
docker compose up --build -d       # levanta Vault, vault-init y los 7 servicios
python -m pytest tests -q          # las pruebas usan .run/secrets.env
docker compose down -v             # detener y borrar datos
```

- Solo el gateway publica el puerto 8000; la red `private` es `internal: true` (sin acceso desde el host ni hacia Internet).
- Verificación rápida: abrir `http://127.0.0.1:8000/health` (debe responder `{"status":"OK",...}`).
- `docker-compose.yml` usa un health check sobre el gateway.

---

## 5. Datos de prueba (ficticios)

Se crean al iniciar:

| Usuario | Rol |
|---|---|
| `cliente_fukusuke` | customer |
| `cliente_dos` | customer |
| `repartidor_maipu` | delivery |
| `admin_fukusuke` | customer + admin |

- **Clave de todos:** el valor de `SEED_PASSWORD` en `.run/secrets.env` (aleatoria, no se versiona).
- **Productos:** 6 (Roll California, Ramen Tonkotsu, Handroll Pollo Teriyaki, Tabla Fukusuke, Gyozas de cerdo, Té verde frío).
- **RUN de prueba válidos:** `11111111-1`, `22222222-2`.

---

## 6. Rutas públicas (gateway, prefijo `/api/v1`)

Toda ruta o verbo fuera de esta lista responde **404**. Los endpoints `/internal/*` no están publicados.

| ID | Verbo y ruta | Acceso | Destino |
|---|---|---|---|
| A01 | POST `/auth/register` | anónimo (10/min por IP) | auth |
| A02 | POST `/auth/login` | anónimo (10/min por IP) | auth |
| A03 | POST `/auth/logout` | sesión | auth |
| S01 | GET `/products` (`?available=true\|false`) | anónimo (campos públicos) | inventory |
| S02 | GET `/products/{id}` | anónimo | inventory |
| S03 | POST `/products` | admin | inventory |
| S04 | PUT `/products/{id}` | admin | inventory |
| S05 | GET `/clients/me` | sesión (propio) | clients |
| S06 | PUT `/clients/me` | sesión (propio) | clients |
| S07 | GET `/clients` | admin (sin RUN ni dirección) | clients |
| S08 | POST `/orders` | sesión | orders |
| S09 | GET `/orders` (`?limite=&offset=`, máx. 50) | sesión (solo propios) | orders |
| S10 | GET `/orders/{id}` | dueño o personal; ajeno → 404 | orders |
| S11 | DELETE `/orders/{id}` | anulación lógica (cliente solo en `pendiente_pago`) | orders |
| S12 | PATCH `/orders/{id}/status` | admin o repartidor según transición | orders |
| S13 | POST `/payments` | sesión (dueño del pedido) | payments |
| S14 | POST `/payments/webhook` | proveedor (firma HMAC) | payments |
| S15 | POST `/graphql` | sesión; autorización por recurso y campo | graphql |

### Permisos por rol

| Rol | Puede |
|---|---|
| Anónimo | Catálogo (S01, S02), registro y login |
| Cliente (customer) | Lo anterior + logout, su perfil, sus pedidos, pagar, GraphQL de sus pedidos |
| Repartidor (delivery) | Ver el detalle de un pedido, marcar `despachado → entregado`, GraphQL (sin `pagoEstado`) |
| Administrador (admin) | Todo: catálogo, listado de clientes, anular y cambiar estados, ver `pagoEstado` |

---

## 7. Probar a mano (PowerShell)

Con el sistema iniciado (`python scripts/run_all.py`), en otra terminal:

```powershell
$base = "http://127.0.0.1:8000/api/v1"
$pw   = (Select-String -Path .run/secrets.env -Pattern "^SEED_PASSWORD=").Line.Split("=",2)[1]

# Login y cabecera de sesión
$login = Invoke-RestMethod -Method Post "$base/auth/login" -ContentType "application/json" `
         -Body (@{username="cliente_fukusuke"; password=$pw} | ConvertTo-Json)
$h = @{ Authorization = "Bearer $($login.access_token)" }

# Catálogo público (sin sesión)
Invoke-RestMethod "$base/products"

# Perfil (requerido antes de crear un pedido)
Invoke-RestMethod -Method Put "$base/clients/me" -Headers $h -ContentType "application/json" -Body (@{
  run="11111111-1"; nombre_completo="Cliente Ficticio"; email="cliente@ejemplo.cl"; telefono="+56912345678";
  direccion="Calle Falsa 123"; comuna="Maipú" } | ConvertTo-Json)

# Crear pedido (el servidor calcula precios y total)
$pedido = Invoke-RestMethod -Method Post "$base/orders" -Headers $h -ContentType "application/json" `
          -Body (@{items=@(@{product_id=1; cantidad=2})} | ConvertTo-Json -Depth 3)
$pedido

# Iniciar pago (solo se envía el id del pedido)
$pago = Invoke-RestMethod -Method Post "$base/payments" -Headers $h -ContentType "application/json" `
        -Body (@{order_id=$pedido.id} | ConvertTo-Json)
$pago

# Resumen agregado por GraphQL
Invoke-RestMethod -Method Post "$base/graphql" -Headers $h -ContentType "application/json" -Body (@{
  query = "query(`$id:Int!){ resumenPedido(id:`$id){ id estado total direccionEntrega pagoEstado detalleDegradado items{ nombre cantidad subtotal categoria } } }"
  variables = @{ id = $pedido.id } } | ConvertTo-Json -Depth 4) | ConvertTo-Json -Depth 8
```

### Confirmar un pago (aviso firmado del proveedor)

El pago solo pasa a `aprobado` con un aviso firmado con HMAC-SHA256 sobre el cuerpo exacto (cabecera `X-Provider-Signature`).
Simulación con Python, usando `provider_ref` y `monto` del paso anterior:

```python
import hashlib, hmac, json, httpx, pathlib
secret = dict(l.split("=", 1) for l in pathlib.Path(".run/secrets.env").read_text().splitlines())["PAYMENTS_WEBHOOK_SECRET"]
raw = json.dumps({"event_id": "evt_demo_001", "provider_ref": "<provider_ref>", "status": "approved", "amount": <monto>}).encode()
sig = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
r = httpx.post("http://127.0.0.1:8000/api/v1/payments/webhook", content=raw,
               headers={"Content-Type": "application/json", "X-Provider-Signature": sig})
print(r.status_code, r.json())   # 200 {'duplicate': False, ...}; repetir el aviso devuelve {'duplicate': True}
```

Con una firma inválida responde 401; con un monto distinto del pedido, 409.

---

## 8. Pruebas

```powershell
python -m pytest tests -q
```

La suite (29 pruebas) se ejecuta contra el sistema en marcha a través del gateway (`GATEWAY_URL`, por defecto
`http://127.0.0.1:8000`). Cubre contratos, propiedad de recursos, roles, acceso directo a servicios privados, rutas fuera de
lista blanca, cabeceras falsas, máquina de estados, stock, pagos duplicados y alterados, `/logout`, validaciones de entrada,
GraphQL (agregación, autorización por campo, límites de profundidad y alias, introspección) y obtención de secretos.

- `tests/test_seguridad.py` — seguridad, contratos, pedidos y pagos
- `tests/test_graphql.py` — agregación y controles GraphQL
- `tests/test_secretos.py` — secretos desde entorno y Vault
- `tests/test_ratelimit.py` — límite de solicitudes (se ejecuta aparte)

**Límite de solicitudes** (bloquea los logins por 60 s; reiniciar el sistema antes de repetir otras pruebas):

```powershell
$env:RUN_RATELIMIT="1"; python -m pytest tests/test_ratelimit.py -q
```

Con `python -m pytest tests -q` esta prueba aparece como `skipped`; es lo esperado (28 pasan + 1 aparte).

### Prueba de carga

Requiere límites altos para que el gateway no responda 429. Detener el sistema (Ctrl+C) y reiniciarlo así:

```powershell
$env:RATE_LIMIT_API="1000000"; $env:RATE_LIMIT_AUTH="1000"; python scripts/run_all.py
# en otra terminal:
python scripts/load_test.py --concurrencia 20 --duracion 15
```

Imprime entorno, concurrencia, duración, throughput, p95, errores y (con `psutil`) CPU y memoria. Los resultados dependen del
equipo: registrar los obtenidos en el informe (Módulo 9) y no reutilizar cifras de otro entorno.

---

## 9. Configuración (variables de entorno)

| Variable | Por defecto | Uso |
|---|---|---|
| `CORS_ORIGINS` | vacío | Orígenes permitidos del frontend, separados por coma (en `gen_env.py`: `https://nicoignaccio.github.io`) |
| `RATE_LIMIT_API` | 120 | Solicitudes por minuto por IP en rutas generales |
| `RATE_LIMIT_AUTH` | 10 | Solicitudes por minuto por IP en `/auth/*` |
| `GRAPHQL_INTROSPECTION` | `false` | `true` habilita la introspección del schema |
| `DATA_DIR` | `./data` | Carpeta de las bases SQLite (una por servicio) |
| `GATEWAY_URL` | `http://127.0.0.1:8000` | Destino de las pruebas |
| `<SERVICIO>_URL` | `http://127.0.0.1:<puerto>` | Dirección de cada servicio (en Docker: nombre del servicio) |
| `VAULT_ADDR`, `VAULT_TOKEN` | — | Si están definidos, los secretos se leen de Vault (`secret/fukusuke`) |
| `MESSAGING_ENABLED` | `false` | `true` publica eventos de pedidos en ActiveMQ (`/queue/pedidos`) |
| `STOMP_HOST`, `STOMP_PORT`, `STOMP_USER`, `STOMP_PASS` | `127.0.0.1`, `61613`, vacío | Conexión STOMP a ActiveMQ |

---

## 10. Secretos (solo referencias; los valores nunca van al repositorio)

| Referencia | Tipo | Consumidor | Finalidad |
|---|---|---|---|
| `AUTH_INTROSPECTION_SECRET` | secreto compartido | gateway → auth | Introspección, login, registro y logout |
| `INVENTORY_SERVICE_SECRET` | credencial de servicio | gateway, orders, graphql → inventory | Acceso a inventory |
| `CLIENTS_SERVICE_SECRET` | credencial de servicio | gateway, orders → clients | Acceso a clients |
| `ORDERS_SERVICE_SECRET` | credencial de servicio | gateway, payments, graphql → orders | Acceso a orders |
| `PAYMENTS_SERVICE_SECRET` | credencial de servicio | gateway, graphql → payments | Acceso a payments |
| `GRAPHQL_SERVICE_SECRET` | credencial de servicio | gateway → graphql | Acceso al GraphQL Gateway |
| `PAYMENTS_WEBHOOK_SECRET` | clave HMAC | payments | Verificar avisos del proveedor |
| `SEED_PASSWORD` | clave de prueba | auth | Solo usuarios ficticios |

- Se generan aleatoriamente (24 bytes) en cada arranque con `run_all.py` o `gen_env.py`; no existen en el código.
- Modo local sin `--vault`: cada proceso recibe únicamente los secretos que necesita (mínimo privilegio, tabla `NEEDS`).
  Con Vault de desarrollo (y en docker compose) todos leen la misma ruta `secret/fukusuke`; en producción se usarían políticas
  AppRole por servicio.
- **Rotación:** no es en caliente; se regeneran los valores y se reinician los procesos (cada proceso conserva en memoria los
  secretos que lee de Vault la primera vez). **Revocación de sesiones:** `POST /auth/logout` o expiración a los 15 minutos.
- Nunca versionar `.env` ni `.run/` (están en `.gitignore`, junto con `data/`).

---

## 11. Seguridad implementada

- Lista blanca de rutas y verbos en el gateway; los servicios privados rechazan (403) toda llamada sin `X-Service-Token`
  correcto y un `X-Caller` autorizado, comparado en tiempo constante.
- El gateway descarta las cabeceras de identidad del navegador y construye `X-User-Id` / `X-User-Roles` desde la
  introspección del token. Los errores 5xx internos se responden como 502/504.
- Contraseñas con PBKDF2-HMAC-SHA256 (600.000 iteraciones, sal de 16 bytes); el login responde igual con o sin usuario.
  Tokens de sesión de 15 min guardados solo como hash SHA-256. `/logout` revoca el token del propio usuario.
- Precios, totales, estados y `user_id` los decide el servidor; los campos extra del navegador se ignoran.
- Un pedido ajeno responde 404 (no permite enumerar ids). El listado administrativo de clientes no incluye RUN ni dirección.
- Pagos: monto tomado de `orders`, aviso con firma HMAC, monto verificado, `event_id` idempotente.
- GraphQL: autorización por campo, profundidad máxima 5, máximo 5 alias, introspección deshabilitada, degradación controlada
  (`detalleDegradado`).
- Límites: 10/min por IP en `/auth/*`, 120/min en el resto, cuerpo máximo 64 KB.

---

## 12. Estructura del proyecto

```
fukusuke-backend/
├── gateway/            API Gateway público (:8000)
├── auth_service/       Autenticación y sesiones (:8100)
├── inventory/          Catálogo y stock (:9001)
├── clients/            Perfiles de clientes (:9002)
├── orders/             Pedidos y estados (:9003)
├── payments/           Pagos y webhook firmado (:9004)
├── graphql_gateway/    Agregación GraphQL privada (:9005)
├── common/             Config/secretos, base de datos, guardia de servicios, mensajería, logging
├── frontend/api.js     Cliente JavaScript del frontend (consume solo el gateway)
├── scripts/            run_all.py, gen_env.py, load_test.py
├── tests/              Suite de integración (pytest)
├── docs/               ADR-001 (analítica y gRPC)
├── docker-compose.yml  Vault, vault-init, servicios y redes public/private
├── Dockerfile
├── requirements.txt
└── .env.example
```

---

## 13. Frontend

`frontend/api.js` es el cliente que consume el gateway (`/api/v1`). Guarda el token en `sessionStorage` y cubre: registro,
login, logout, catálogo, perfil, crear y anular pedido, iniciar pago y `resumenPedido`. Las funciones para S02, S03, S04, S07,
S09, S10 y S12 (historial, administración y reparto) se agregan junto con esas pantallas; el backend ya expone todos los
servicios. Para usarlo desde un sitio publicado, incluir su origen en `CORS_ORIGINS`.

---

## 14. Health checks y logs

Cada servicio expone `GET /health`; `run_all.py` lo usa para esperar el arranque. Los logs incluyen un identificador de
correlación (`rid`, cabecera `X-Request-Id`) y solo método, ruta (sin query), estado y duración: nunca cabeceras, cuerpos,
tokens ni datos personales.

---

## 15. Solución de problemas

| Síntoma | Causa probable | Solución |
|---|---|---|
| `Falta .run/secrets.env` al correr pytest | El sistema no se ha iniciado | Ejecutar `python scripts/run_all.py` primero (o `gen_env.py` en Docker) |
| `El servicio X no respondió` | Puerto ocupado o falta una dependencia | Cerrar procesos previos, revisar `pip install -r requirements.txt` |
| Respuestas 429 en las pruebas | Límite de solicitudes por IP | Esperar 60 s o reiniciar el sistema |
| 429 en la prueba de carga | Límites no elevados | Reiniciar con `RATE_LIMIT_API=1000000` |
| 401 en rutas protegidas | Token expirado (15 min) o cerrado | Volver a iniciar sesión |
| 409 al crear pedido | Stock insuficiente o perfil incompleto | Completar `PUT /clients/me` o bajar la cantidad |
| Error de CORS en el navegador | Origen no permitido | Agregar el origen del frontend a `CORS_ORIGINS` y reiniciar |
| `docker compose up` falla | Falta `.env` | Ejecutar `python scripts/gen_env.py` antes |

---

## 16. Limitaciones declaradas

- TLS no está habilitado en esta demo (se terminaría en el gateway o un proxy inverso en producción).
- Las sesiones viven en la SQLite de auth y el límite de solicitudes en memoria: es coherente con un único gateway.
- No hay rotación de secretos en caliente ni eliminación automática de datos personales (se atiende a solicitud del titular).
- El proveedor de pagos es un adaptador de prueba: se simula con avisos firmados (ver `tests/test_seguridad.py`).
- Analítica y gRPC no se implementan por decisión justificada en `docs/ADR-001-analitica-y-grpc.md`.
- No hay reporte de ventas implementado; quedaría como consulta agregada en `orders`, solo para admin.
