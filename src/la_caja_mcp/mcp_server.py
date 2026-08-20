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
import sys
import uuid
from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field
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
    claim: Annotated[str, Field(description="El claim a debatir, en texto plano. Es el objeto del debate que los participantes deben aceptar/refutar.")],
    participantes: Annotated[list[str], Field(description="Lista de identidades (ej. ['claude', 'asesor']). El arbitro, si se indica, se anade aparte y no juega.")],
    arbitro: Annotated[str | None, Field(description="Identidad del humano/arbitro que puede desempatar con adjudicar. Si es None, no hay arbitro.")] = None,
    contexto: Annotated[str, Field(description="Contexto extra opcional del debate (p. ej. memorias o notas previas). Vacio si no hay.")] = "",
    limite_turnos: Annotated[int, Field(description="Rondas maximas de discusion antes de que el deadline venza (vence_en_turnos llega a 0). Minimo 1.")] = 3,
) -> dict:
    """Crea una sesion de debate sobre un claim y devuelve su estado inicial.

    Es un movimiento de mutacion: crea una nueva sesion en memoria. No
    requiere sesion previa (es la entrada del flujo). El primer movimiento
    que debe emitir un participante es proponer(actor); si el claim ya
    existe en otra sesion, las sesiones son independientes.

    Devuelve: sesion_id (hex unico, usar en mover/estado/ultimos_eventos)
    y el estado inicial (fase 'propuesta', sin eventos).
    """
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
async def mover(
    sesion_id: Annotated[str, Field(description="Id de la sesion (el sesion_id que devolvio crear_sesion).")],
    tipo: Annotated[str, Field(description="Movimiento: proponer | aceptar | interferir | responder | condiciones | adjudicar | supersede | retirar | escalar | manifestar. Cada tipo tiene su payload (ver payload).")],
    actor: Annotated[str, Field(description="Identidad de quien mueve. Debe estar en participantes (o ser el arbitro para adjudicar).")],
    payload: Annotated[str, Field(description="JSON string con las claves del tipo: interferir:{objecion}, responder:{defensa}, condiciones:{lista}, adjudicar:{decision:'consensus'|'rejected'|'unresolved'}, supersede:{reemplazo}, manifestar:{texto}. proponer/aceptar/retirar/escalar: vacio o {}.")] = "",
) -> dict:
    """Aplica un movimiento de debate a la sesion y devuelve el evento + estado.

    Mutacion. Valida el movimiento contra la maquina de estados (si el
    tipo no es valido en la fase actual, o el actor no corresponde,
    devuelve ok=False con el error del protocolo). Si hay suscriptores SSE
    en /caja/push, les emite un evento sesion_actualizada (no bloquea).

    Devuelve: ok (bool), evento (el evento con seq), estado (snapshot con
    fase, vence_en_turnos, etc.). En error: ok=False y campo error.
    """
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
async def estado(
    sesion_id: Annotated[str, Field(description="Id de la sesion (el sesion_id que devolvio crear_sesion).")],
) -> dict:
    """Devuelve el estado actual de la sesion mas el log completo de eventos.

    Lectura pura: no muta nada y no requiere estar en la ronda. Es el
    equivalente a 'snapshot total'. Para solo los eventos nuevos desde un
    seq, usa ultimos_eventos (mas barato); para reconstruir una sesion
    desde un log externo, usa reproducir_sesion.

    Devuelve: ok, estado (fase, claim, vence_en_turnos, participantes,
    arbitro) y log (lista completa de eventos con seq, replayable).
    """
    async with _lock:
        try:
            sesion = _get(sesion_id)
            return _ok(estado=sesion.estado_actual(), log=sesion.log)
        except ErrorDeProtocolo as e:
            return _error(e)


@mcp.tool
async def ultimos_eventos(
    sesion_id: Annotated[str, Field(description="Id de la sesion (el sesion_id que devolvio crear_sesion).")],
    desde_seq: Annotated[int, Field(description="Solo eventos con seq mayor a este numero. Usa el ultimo_seq que viste para hacer sondeo incremental. Default 0 = todos.")] = 0,
) -> dict:
    """Devuelve los eventos con seq mayor a desde_seq (sondeo incremental).

    Lectura pura. Es la primitiva de polling para la discusion en vivo:
    tras recibir un push SSE (o en stdio, periodicamente), trae solo lo
    nuevo. Para el log completo usa estado; para reconstruir, reproducir_sesion.

    Devuelve: ok, eventos (lista, puede ser vacia) y ultimo_seq (el max
    seq actual, para el proximo desde_seq).
    """
    async with _lock:
        try:
            sesion = _get(sesion_id)
            eventos = [e for e in sesion.log if e["seq"] > desde_seq]
            return _ok(eventos=eventos, ultimo_seq=sesion.log[-1]["seq"] if sesion.log else 0)
        except ErrorDeProtocolo as e:
            return _error(e)


@mcp.tool
async def reproducir_sesion(
    claim: Annotated[str, Field(description="El claim original del debate (debe coincidir con el del log; se usa para validar el replay).")],
    log: Annotated[str, Field(description="String JSON que es una LISTA de eventos (los que devolvio estado/ultimos_eventos). El orden importa: se replaya en secuencia.")],
) -> dict:
    """Reconstruye una sesion replayando un log de eventos y verifica determinismo.

    Lectura pura: no crea una sesion nueva ni toca las existentes. El
    resultado del replay debe ser identico al estado original de la sesion
    que genero el log (disciplina event-sourcing de La Caja). Sirve para
    auditar o reproducir un debate fuera del server.

    Devuelve: ok, estado (reconstruido) y n_eventos (cuantos se
    reprodujeron). En error: ok=False con la causa (log invalido, claim no
    coincide, secuencia invalida).
    """
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
async def procesar_consulta(
    texto: Annotated[str, Field(description="La consulta o texto crudo a ingestar en La Caja, en texto plano (ej. una frase completa del usuario o del contexto). No requiere formato especial.")],
) -> dict:
    """Ingesta: procesa un texto completo en La Caja y actualiza la memoria.

    Mutacion: tokeniza el texto, normaliza a conceptos canonicos, filtra
    ruido y crea/reforza las burbujas del contexto (co-ocurrencias). El
    efecto es persistente si el server corre con --caja-db (o LA_CAJA_DB);
    si no, es en memoria pura y se pierde al reiniciar. Requiere el
    paquete `la-caja` instalado; si no, devuelve ok=False con el error.

    Es el paso previo natural a declarar_relacion (que declara a mano lo
    que aqui se extrae automatico). Para solo leer, usa consultar o
    contexto_primado.

    Devuelve: ok y el resultado del procesado (terminos procesados y
    eventos de la piscina).
    """
    caja = _get_caja()
    if caja is None:
        return {"ok": False, "error": _caja_error}
    async with _lock:
        return {"ok": True, **caja.procesar_consulta(texto)}


@mcp.tool
async def declarar_relacion(
    a: Annotated[str, Field(description="Primer termino de la relacion (concepto canonico, ej. 'postgres').")],
    b: Annotated[str, Field(description="Segundo termino de la relacion (concepto canonico, ej. 'replica').")],
) -> dict:
    """Declara una co-ocurrencia explicita entre dos terminos sin texto crudo.

    Mutacion: crea (o refuerza) la arista a-b en la memoria, sin pasar por
    la ingesta de texto. Util para scripting e integraciones donde ya
    sabes la relacion. Para extraer relaciones automaticamente de texto,
    usa procesar_consulta. Para leer la confianza de una relacion, usa
    consultar.

    Devuelve: ok, a, b y eventos (los eventos de memoria generados).
    """
    caja = _get_caja()
    if caja is None:
        return {"ok": False, "error": _caja_error}
    async with _lock:
        eventos = caja.declarar_relacion(a, b)
        return {"ok": True, "a": a, "b": b, "eventos": eventos}


@mcp.tool
async def consultar(
    a: Annotated[str, Field(description="Primer termino (concepto canonico). Debe existir en la memoria o devuelve 0.0.")],
    b: Annotated[str, Field(description="Segundo termino (concepto canonico). Debe existir en la memoria o devuelve 0.0.")],
) -> dict:
    """Devuelve la confianza de la relacion entre dos terminos.

    Lectura pura, no muta nada. Confianza: 1.0 si fue observada, 0.5^puentes
    si fue inferida por cierre transitivo, 0.0 si no hay relacion. Solo
    mira relaciones activas (la traza dormida no cuenta; usa historial).

    Devuelve: ok, a, b y confianza (float 0..1).
    """
    caja = _get_caja()
    if caja is None:
        return {"ok": False, "error": _caja_error}
    async with _lock:
        return {"ok": True, "a": a, "b": b, "confianza": caja.consultar(a, b)}


@mcp.tool
async def contexto_primado(
    termino: Annotated[str, Field(description="Termino cuyo contexto asociativo queres (concepto canonico).")],
    presupuesto: Annotated[int, Field(description="Cantidad maxima de relaciones a incluir en el contexto (acota el tamano del primado). Default 50.")] = 50,
) -> dict:
    """Devuelve el contexto asociativo de un termino para inyectar en un modelo.

    Lectura pura. Es el mecanismo de primado: arma un bloque de contexto
    con las relaciones observadas primero (mas confiables) y luego el
    vecindario de activacion, acotado al presupuesto. Es la pieza que
    mejoro el recall en el benchmark (soporte de memoria).

    Distinto de la navegacion (consultar, que responde por termino) y de
    historial (traza dormida). Para primar la memoria de un agente antes
    de responder, usa esto.

    Devuelve: ok, termino y primado (la estructura de contexto asociativo).
    """
    caja = _get_caja()
    if caja is None:
        return {"ok": False, "error": _caja_error}
    async with _lock:
        return {"ok": True, "termino": termino, "primado": caja.contexto_primado(termino, presupuesto)}


@mcp.tool
async def historial(
    termino: Annotated[str, Field(description="Termino cuyo historial (traza dormida) queres (concepto canonico).")],
) -> dict:
    """Devuelve la traza dormida de un termino (capa inerte de la memoria).

    Lectura pura. Muestra los partners con los que el termino co-ocurrio y
    fue olvidado (por consolidacion), con su fuerza historica. Esta capa
    NO participa en consultar ni en contexto_primado: es inerte hasta que
    una re-observacion la rehidrata. Util para entender que se olvido, no
    para recuperar contexto activo.

    Devuelve: ok, termino y historial (partners dormidos con fuerza).
    """
    caja = _get_caja()
    if caja is None:
        return {"ok": False, "error": _caja_error}
    async with _lock:
        return {"ok": True, "termino": termino, "historial": caja.historial(termino)}


@mcp.tool
async def stats() -> dict:
    """Devuelve las dimensiones de la memoria (terminos, nodos, aristas).

    Lectura pura, sin parametros. Sirve para monitorear el tamano de la
    memoria. Para inspeccionar contenido puntual usa consultar,
    contexto_primado o historial.

    Devuelve: ok y dimensiones (terminos, nodos, aristas).
    """
    caja = _get_caja()
    if caja is None:
        return {"ok": False, "error": _caja_error}
    async with _lock:
        return {"ok": True, **caja.stats()}


app = mcp.http_app(transport="streamable-http")
app.add_route("/caja/push", _push_sse, methods=["GET"])


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "install":
        from la_caja_mcp.install import main as install_main

        raise SystemExit(install_main(sys.argv[2:]))
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