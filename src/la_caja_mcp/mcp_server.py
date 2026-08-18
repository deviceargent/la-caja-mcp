"""Servidor MCP del protocolo de debate. Un juego de tools, dos
transportes: stdio (local) y streamable HTTP (remoto).

Las sesiones viven en memoria (prototipo). El log de eventos es el
artefacto durable: una sesion se reconstruye con reproducir_sesion
replayando el log (disciplina de La Caja).

Sobre el payload de mover(): es un string JSON con las claves que cada
tipo espera:
- interferir: {"objecion": str}
- responder: {"defensa": str}
- condiciones: {"lista": [str, ...]}
- adjudicar: {"decision": "consensus"|"rejected"|"unresolved"}
- supersede: {"reemplazo": str}
- manifestar: {"texto": str}
- proponer/aceptar/retirar/escalar: sin payload
"""

from __future__ import annotations

import argparse
import json
import threading
import uuid

from fastmcp import FastMCP

from la_caja_mcp.protocolo import ErrorDeProtocolo, Sesion

mcp = FastMCP("la-caja-debate")

_sesiones: dict[str, Sesion] = {}
_lock = threading.Lock()


def _get(sesion_id: str) -> Sesion:
    sesion = _sesiones.get(sesion_id)
    if sesion is None:
        raise ErrorDeProtocolo(f"sesion desconocida: {sesion_id!r}")
    return sesion


def _parse_payload(payload: str) -> dict:
    if not payload.strip():
        return {}
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as e:
        raise ErrorDeProtocolo(f"payload JSON invalido: {e}")
    if not isinstance(data, dict):
        raise ErrorDeProtocolo("payload debe ser un objeto JSON")
    return data


def _ok(**data):
    return {"ok": True, **data}


def _error(exc: ErrorDeProtocolo):
    return {"ok": False, "error": str(exc)}


@mcp.tool
def crear_sesion(
    claim: str,
    participantes: list[str],
    arbitro: str | None = None,
    contexto: str = "",
    limite_turnos: int = 3,
) -> dict:
    """Crea una sesion de debate sobre un claim. Devuelve sesion_id y el
    estado inicial. El primer movimiento es proponer(actor)."""
    with _lock:
        sesion = Sesion(
            claim=claim,
            contexto=contexto,
            participantes=participantes,
            arbitro=arbitro,
            limite_turnos=limite_turnos,
        )
        sesion_id = uuid.uuid4().hex
        _sesiones[sesion_id] = sesion
        return _ok(sesion_id=sesion_id, estado=sesion.estado_actual())


@mcp.tool
def mover(sesion_id: str, tipo: str, actor: str, payload: str = "") -> dict:
    """Aplica un movimiento a la sesion. Ver docstring del modulo para el
    payload JSON que espera cada tipo. Devuelve el evento y el estado."""
    with _lock:
        try:
            sesion = _get(sesion_id)
            evento = sesion.mover(tipo, actor, **_parse_payload(payload))
            return _ok(evento=evento, estado=sesion.estado_actual())
        except ErrorDeProtocolo as e:
            return _error(e)


@mcp.tool
def estado(sesion_id: str) -> dict:
    """Estado actual de la sesion mas el log completo de eventos
    (replayable)."""
    with _lock:
        try:
            sesion = _get(sesion_id)
            return _ok(estado=sesion.estado_actual(), log=sesion.log)
        except ErrorDeProtocolo as e:
            return _error(e)


@mcp.tool
def ultimos_eventos(sesion_id: str, desde_seq: int = 0) -> dict:
    """Eventos con seq mayor a desde_seq. Primitiva de sondeo para
    discusion en vivo: un agente pregunta que paso desde su ultimo corte."""
    with _lock:
        try:
            sesion = _get(sesion_id)
            eventos = [e for e in sesion.log if e["seq"] > desde_seq]
            return _ok(eventos=eventos, ultimo_seq=sesion.log[-1]["seq"] if sesion.log else 0)
        except ErrorDeProtocolo as e:
            return _error(e)


@mcp.tool
def reproducir_sesion(claim: str, log: str) -> dict:
    """Reconstruye una sesion replayando un log de eventos (JSON list).
    Verifica determinismo: el estado final debe coincidir con el que
    produjeron los eventos originales."""
    with _lock:
        try:
            eventos = json.loads(log)
            if not isinstance(eventos, list):
                raise ErrorDeProtocolo("log debe ser una lista JSON")
            sesion = Sesion.reproducir(eventos)
            return _ok(estado=sesion.estado_actual(), n_eventos=len(sesion.log))
        except ErrorDeProtocolo as e:
            return _error(e)
        except json.JSONDecodeError as e:
            return {"ok": False, "error": f"log JSON invalido: {e}"}


app = mcp.http_app(transport="streamable-http")


def main() -> None:
    parser = argparse.ArgumentParser(prog="la-caja-mcp")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default="stdio",
        help="transportes: stdio (local) o streamable-http (remoto)",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--path", default=None)
    args = parser.parse_args()
    if args.transport == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.run(
            transport="streamable-http",
            host=args.host,
            port=args.port,
            path=args.path,
        )


if __name__ == "__main__":
    main()
