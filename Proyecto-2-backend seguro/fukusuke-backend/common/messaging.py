"""Publicación best-effort de eventos de pedido en ActiveMQ (STOMP), como en la Semana 10."""
import json
import logging
import os

log = logging.getLogger("messaging")


def publish_event(evento: dict) -> None:
    if os.getenv("MESSAGING_ENABLED", "false").lower() != "true":
        return
    try:
        import stomp
        conn = stomp.Connection12([(os.getenv("STOMP_HOST", "127.0.0.1"), int(os.getenv("STOMP_PORT", "61613")))])
        conn.connect(os.getenv("STOMP_USER", ""), os.getenv("STOMP_PASS", ""), wait=True)
        conn.send(destination="/queue/pedidos", body=json.dumps(evento),
                  headers={"content-type": "application/json", "x-formato": "json", "persistent": "true"})
        conn.disconnect()
    except Exception as e:  # la mensajería nunca debe romper la transacción del pedido
        log.warning("No se pudo publicar evento: %s", type(e).__name__)
