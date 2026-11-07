# ADR-001: Servicio de analítica y gRPC no se implementan en esta versión

**Estado:** aceptada · **Caso:** 19 – Fukusuke Sushi-Delivery

## Contexto
El caso es un sistema de ventas y delivery de un restaurante. Operaciones: catálogo (decenas de productos), pedidos y pagos de
una sola sucursal. Los mensajes entre servicios son pequeños (< 2 KB), sin streaming. El único reporte del caso (ventas por
período) consulta los pedidos de `orders` y su volumen se proyecta en cientos de pedidos por día (**proyección**, no medición).

## Alternativas
1. Servicio de analítica separado con ETL y almacén propio (big data).
2. gRPC entre `orders`, `inventory` y `payments`.
3. REST interno + GraphQL Gateway; reportes como consulta agregada paginada sobre `orders` (**elegida**).

## Decisión
No implementar (1) ni (2). Mantener REST interno con secretos de servicio y la agregación GraphQL. Los reportes futuros se
resuelven con una consulta agregada en `orders` (índices por fecha/estado) expuesta solo a administradores.

## Consecuencias
- Menos componentes que operar y proteger; contratos REST simples de probar.
- Se asume un volumen bajo: **debe verificarse con `scripts/load_test.py`** (p95 y errores en la tabla del informe).
- Reabrir esta decisión si aparecen: más de ~50 pedidos/minuto sostenidos, seguimiento de despacho en tiempo real
  (streaming de servidor gRPC con adaptación a SSE/WebSocket para el navegador), o reportes que no quepan en la base transaccional.
- Mensajería asíncrona (ActiveMQ/STOMP, Semana 10): `orders` publica eventos de ciclo de vida en `/queue/pedidos` si
  `MESSAGING_ENABLED=true`; es complementaria y nunca bloquea la transacción del pedido.
