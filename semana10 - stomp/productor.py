import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation

import stomp

COLA_DESTINO = "/queue/pedidos"


def parsear_argumentos():
    p = argparse.ArgumentParser(description="Productor de pedidos Fukusuke Sushi (STOMP / ActiveMQ)")
    p.add_argument("--formato", choices=["texto", "fijo", "xml", "json"], default="json")
    p.add_argument("--mensaje", help="Texto plano (formato texto)")
    p.add_argument("--id", type=int, help="ID del pedido")
    p.add_argument("--cliente", help="Nombre del cliente")
    p.add_argument("--monto", help="Monto del pedido (ej. 12990.50)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=61613)
    p.add_argument("--usuario", default=os.getenv("STOMP_USER", "admin"))
    p.add_argument("--clave", default=os.getenv("STOMP_PASS", "admin"))
    return p.parse_args()


def validar_pedido(args):
    if args.id is None or not args.cliente or args.monto is None:
        raise ValueError("Para este formato se requieren --id, --cliente y --monto")
    try:
        monto = Decimal(args.monto)
    except InvalidOperation:
        raise ValueError(f"Monto inválido: {args.monto}")
    if monto <= 0:
        raise ValueError("El monto debe ser mayor que cero")
    return {"id": args.id, "cliente": args.cliente, "monto": monto.quantize(Decimal("0.01"))}


def construir_mensaje(args):
    """Retorna (body, content_type) según el formato elegido."""
    if args.formato == "texto":
        if not args.mensaje:
            raise ValueError("El formato texto requiere --mensaje")
        return args.mensaje, "text/plain"

    pedido = validar_pedido(args)

    if args.formato == "json":
        return json.dumps({**pedido, "monto": str(pedido["monto"])}, ensure_ascii=False), "application/json"

    if args.formato == "xml":
        raiz = ET.Element("pedido")
        ET.SubElement(raiz, "id").text = str(pedido["id"])
        ET.SubElement(raiz, "cliente").text = pedido["cliente"]
        ET.SubElement(raiz, "monto").text = str(pedido["monto"])
        return ET.tostring(raiz, encoding="unicode"), "application/xml"

    centavos = int(pedido["monto"] * 100)
    cuerpo = f"{pedido['id']:08d}{pedido['cliente'][:30]:<30}{centavos:012d}"
    return cuerpo, "text/plain"


def main():
    args = parsear_argumentos()
    try:
        body, content_type = construir_mensaje(args)
    except ValueError as e:
        print(f"Error de validación: {e}", file=sys.stderr)
        sys.exit(1)

    conexion = stomp.Connection12([(args.host, args.port)])
    try:
        conexion.connect(args.usuario, args.clave, wait=True)
        conexion.send(
            destination=COLA_DESTINO,
            body=body,
            headers={
                "content-type": content_type,
                "x-formato": args.formato,
                "persistent": "true",
            },
        )
        print(f"Mensaje enviado a {COLA_DESTINO} [{args.formato}]: {body}")
    except Exception as e:
        print(f"Error al enviar al broker: {e}", file=sys.stderr)
        sys.exit(2)
    finally:
        if conexion.is_connected():
            conexion.disconnect()


if __name__ == "__main__":
    main()
