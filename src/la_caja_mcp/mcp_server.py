"""Servidor MCP de la-caja-mcp: protocolo de debate + memoria de La Caja.
Un juego de tools, dos transportes: stdio (local) y streamable HTTP
(remoto).

Las sesiones de debate viven en memoria (prototipo). El log de eventos
es el artefacto durable: una sesion se reconstruye con reproducir_sesion
replayando el log (disciplina de La Caja).

DISCUSION EN VIVO: en streamable HTTP, el server expone un endpoint SSE
adicional  GET /caja/push?sesion_id=<id>  que emite un evento inicial
"estado" (snapshot: ultimo_seq + estado) y luego un evento
"sesion_actualizada" (mismo schema) por cada mover() exitoso. Un agente
se suscribe con una conexion HTTP extra (cualquier stack) y usa
ultimos_eventos para traer el detalle. En stdio cada agente tiene su
propio proceso (no hay server compartido): ahi la vivacidad es por
sondeo con ultimos_eventos.

Las tools de memoria consumen el paquete `la-caja` (repo A). Si no esta
instalado, responden con error claro sin romper el server. La memoria es
persistente si se pasa --caja-db <ruta> (o LA_CAJA_DB); sin eso, queda
en memoria pura.

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
import asyncio
import json
import os
import uuid

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse

from la_caja_mcp.protocolo import ErrorDeProtocolo, Sesion

mcp = FastMCP("la-caja-debate")

_sesiones: dict[str, Sesion] = {}
_lock = asyncio.Lock()
_pushers: dict[str, set[asyncio.Queue]] = {}

_caja_db: str | None = None
_caja = None
_caja_error: str | None = None


def _get_caja():
    """Instancia lazy de La Caja. Devuelve None con _caja_error seteado
    si el paquete no esta instalado."""
    global _caja, _caja_error
    if _caja_error is not None:
        return None
    if _caja is None:
        try:
            from la_caja.core import LaCaja
        except ImportError:
            _caja_error = (
                "la-caja no esta instalado (pip install la-caja). "
                "Las tools de memoria quedan desactivadas."
            )
            return None
        _caja = LaCaja(db_path=_caja_db)
    return _caja


def set_caja_db(ruta: str | None) -> None:
    global _caja_db
    _caja_db = ruta or os.environ.get("LA_CAJA_DB")


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


def _estado_publico(sesion_id: str) -> dict:
    sesion = _sesiones[sesion_id]
    return {
        "sesion_id": sesion_id,
        "ultimo_seq": sesion.log[-1]["seq"] if sesion.log else 0,
        "estado": sesion.estado,
    }


def _publish(sesion_id: str) -> None:
    """Empuja un evento sesion_actualizada a los suscriptores SSE de la
    sesion (put_nowait: no bloquea el flujo de mover)."""
    queues = _pushers.get(sesion_id)
    if not queues:
        return
    payload = json.dumps(_estado_publico(sesion_id), ensure_ascii=False)
    for q in list(queues):
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            pass


async def _push_sse(request: Request):
    sesion_id = request.query_params.get("sesion_id", "")
    if sesion_id not in _sesiones:
        return JSONResponse({"error": "sesion desconocida"}, status_code=404)
    q: asyncio.Queue = asyncio.Queue()
    _pushers.setdefault(sesion_id, set()).add(q)

    async def gen():
        try:
            yield "retry: 2000\n\n"
            yield f"event: estado\ndata: {json.dumps(_estado_publico(sesion_id), ensure_ascii=False)}\n\n"
            while True:
                payload = await q.get()
                yield f"event: sesion_actualizada\ndata: {payload}\n\n"
        finally:
            _pushers.get(sesion_id, set()).discard(q)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@mcp.tool
async def crear_sesion(
    claim: str,
    participantes: list[str],
    arbitro: str | None = None,
    contexto: str = "",
    limite_turnos: int = 3,
) -> dict:
    """Crea una sesion de debate sobre un claim. Devuelve sesion_id y el
    estado inicial. El primer movimiento es proponer(actor)."""
    async with _lock:
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
async def mover(sesion_id: str, tipo: str, actor: str, payload: str = "") -> dict:
    """Aplica un movimiento a la sesion. Si hay suscriptores SSE en
    /caja/push, les emite sesion_actualizada. Devuelve el evento y el
    estado."""
    async with _lock:
        try:
            sesion = _get(sesion_id)
            evento = sesion.mover(tipo, actor, **_parse_payload(payload))
            estado = sesion.estado_actual()
        except ErrorDeProtocolo as e:
            return _error(e)
    _publish(sesion_id)
    return _ok(evento=evento, estado=estado)


@mcp.tool
async def estado(sesion_id: str) -> dict:
    """Estado actual de la sesion mas el log completo de eventos
    (replayable)."""
    async with _lock:
        try:
            sesion = _get(sesion_id)
            return _ok(estado=sesion.estado_actual(), log=sesion.log)
        except ErrorDeProtocolo as e:
            return _error(e)


@mcp.tool
async def ultimos_eventos(sesion_id: str, desde_seq: int = 0) -> dict:
    """Eventos con seq mayor a desde_seq. Primitiva de sondeo para la
    discusion: tras un push, un agente trae los eventos nuevos."""
    async with _lock:
        try:
            sesion = _get(sesion_id)
            eventos = [e for e in sesion.log if e["seq"] > desde_seq]
            return _ok(eventos=eventos, ultimo_seq=sesion.log[-1]["seq"] if sesion.log else 0)
        except ErrorDeProtocolo as e:
            return _error(e)


@mcp.tool
async def reproducir_sesion(claim: str, log: str) -> dict:
    """Reconstruye una sesion replayando un log de eventos (JSON list).
    Verifica determinismo: el estado final debe coincidir con el que
    produjeron los eventos originales."""
    async with _lock:
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


@mcp.tool
async def procesar_consulta(texto: str) -> dict:
    """Ingesta: procesa una consulta humana completa en La Caja
    (tokeniza, normaliza a conceptos canonicos, filtra y crea/reforza
    las burbujas del contexto). Devuelve los terminos procesados y los
    eventos de la piscina."""
    caja = _get_caja()
    if caja is None:
        return {"ok": False, "error": _caja_error}
    async with _lock:
        return {"ok": True, **caja.procesar_consulta(texto)}


@mcp.tool
async def declarar_relacion(a: str, b: str) -> dict:
    """Declara una relacion entre dos terminos (co-ocurrencia explicita)
    sin pasar por texto crudo. Util para scripting e integraciones."""
    caja = _get_caja()
    if caja is None:
        return {"ok": False, "error": _caja_error}
    async with _lock:
        eventos = caja.declarar_relacion(a, b)
        return {"ok": True, "a": a, "b": b, "eventos": eventos}


@mcp.tool
async def consultar(a: str, b: str) -> dict:
    """Confianza de la relacion entre dos terminos: 1.0 observada,
    0.5^puentes inferida por cierre transitivo, 0.0 sin relacion."""
    caja = _get_caja()
    if caja is None:
        return {"ok": False, "error": _caja_error}
    async with _lock:
        return {"ok": True, "a": a, "b": b, "confianza": caja.consultar(a, b)}


@mcp.tool
async def contexto_primado(termino: str, presupuesto: int = 50) -> dict:
    """Contexto asociativo de un termino para inyectar en un modelo:
    las relaciones observadas primero, luego el vecindario de activacion,
    acotado al presupuesto. Mecanismo separado de la navegacion."""
    caja = _get_caja()
    if caja is None:
        return {"ok": False, "error": _caja_error}
    async with _lock:
        return {"ok": True, "termino": termino, "primado": caja.contexto_primado(termino, presupuesto)}


@mcp.tool
async def stats() -> dict:
    """Dimensiones de la memoria: terminos, nodos, aristas."""
    caja = _get_caja()
    if caja is None:
        return {"ok": False, "error": _caja_error}
    async with _lock:
        return {"ok": True, **caja.stats()}


app = mcp.http_app(transport="streamable-http")
app.add_route("/caja/push", _push_sse, methods=["GET"])


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
    parser.add_argument(
        "--caja-db",
        default=None,
        help="ruta a la memoria persistente de La Caja (SQLite); si no, "
        "en memoria pura (o LA_CAJA_DB)",
    )
    args = parser.parse_args()
    set_caja_db(args.caja_db)
    if args.transport == "stdio":
        mcp.run(transport="stdio")
    else:
        import uvicorn

        uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()