import argparse
import json
import os
import time
import xml.etree.ElementTree as ET
from decimal import Decimal

import stomp

COLA_DESTINO = "/queue/pedidos"


def desempaquetar(formato, body):
    if formato == "texto":
        return {"mensaje": body}

    if formato == "json":
        datos = json.loads(body)
        return {"id": datos["id"], "cliente": datos["cliente"], "monto": Decimal(datos["monto"])}

    if formato == "xml":
        raiz = ET.fromstring(body)
        return {
            "id": int(raiz.findtext("id")),
            "cliente": raiz.findtext("cliente"),
            "monto": Decimal(raiz.findtext("monto")),
        }

    if formato == "fijo":
        return {
            "id": int(body[0:8]),
            "cliente": body[8:38].strip(),
            "monto": Decimal(int(body[38:50])) / 100,
        }

    raise ValueError(f"Formato desconocido: {formato}")


class PedidosListener(stomp.ConnectionListener):
    def on_message(self, frame, message=None):
        headers = frame.headers if hasattr(frame, "headers") else frame
        body = frame.body if hasattr(frame, "body") else message
        formato = headers.get("x-formato", "texto")

        print(f"\n--- Mensaje recibido [{formato}] ({headers.get('content-type')}) ---")
        try:
            print(desempaquetar(formato, body))
        except (ValueError, KeyError, ET.ParseError, TypeError) as e:
            print(f"No se pudo procesar el mensaje: {e}\nCuerpo crudo: {body}")

    def on_error(self, frame, message=None):
        cuerpo = frame.body if hasattr(frame, "body") else message
        print(f"Error del broker: {cuerpo}")

    def on_disconnected(self):
        print("Desconectado del broker")


def main():
    p = argparse.ArgumentParser(description="Consumidor de pedidos Fukusuke Sushi (STOMP / ActiveMQ)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=61613)
    p.add_argument("--usuario", default=os.getenv("STOMP_USER", "admin"))
    p.add_argument("--clave", default=os.getenv("STOMP_PASS", "admin"))
    args = p.parse_args()

    conexion = stomp.Connection12([(args.host, args.port)])
    conexion.set_listener("pedidos", PedidosListener())
    conexion.connect(args.usuario, args.clave, wait=True)
    conexion.subscribe(destination=COLA_DESTINO, id=1, ack="auto")
    print(f"Escuchando {COLA_DESTINO}... (Ctrl+C para salir)")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        if conexion.is_connected():
            conexion.disconnect()


if __name__ == "__main__":
    main()
