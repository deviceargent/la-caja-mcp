"""Integracion: un cliente MCP real (stdio) contra el server procesa el
debate completo y verifica replay y rechazo de movimientos invalidos."""

import asyncio
import json
import os
import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CLAIM = "la caja recupera asociaciones observadas con confianza"


def _texto(resultado):
    for bloque in resultado.content:
        if bloque.type == "text":
            return json.loads(bloque.text)
    raise AssertionError(f"sin contenido de texto: {resultado}")


async def _sesion_y_cliente():
    env = dict(os.environ)
    env["PYTHONPATH"] = os.path.join(ROOT, "src")
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "la_caja_mcp.mcp_server", "--transport", "stdio"],
        env=env,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


async def _debatir(session, sid):
    for tipo, actor, payload in [
        ("proponer", "claude", "{}"),
        ("interferir", "asesor", '{"objecion": "presupuesto corta la senal"}'),
        ("responder", "claude", '{"defensa": "subimos a 50"}'),
        ("condiciones", "asesor", '{"lista": ["presupuesto 50", "C2 por techo"]}'),
        ("aceptar", "asesor", "{}"),
    ]:
        r = await session.call_tool(
            "mover", {"sesion_id": sid, "tipo": tipo, "actor": actor, "payload": payload}
        )
        mover = _texto(r)
        assert mover["ok"], mover


def test_debate_completo_y_replay_por_stdio():
    async def run():
        async for session in _sesion_y_cliente():
            r = await session.call_tool(
                "crear_sesion",
                {"claim": CLAIM, "participantes": ["claude", "asesor", "humano"], "arbitro": "humano"},
            )
            crear = _texto(r)
            assert crear["ok"], crear
            sid = crear["sesion_id"]

            await _debatir(session, sid)

            r = await session.call_tool("estado", {"sesion_id": sid})
            estado = _texto(r)
            assert estado["estado"]["estado"] == "consensus"

            log = json.dumps(estado["log"], ensure_ascii=False)
            r = await session.call_tool("reproducir_sesion", {"claim": CLAIM, "log": log})
            replay = _texto(r)
            assert replay["ok"] and replay["estado"]["estado"] == "consensus"

            r = await session.call_tool(
                "mover", {"sesion_id": sid, "tipo": "escalar", "actor": "asesor"}
            )
            assert _texto(r)["ok"] is False

    asyncio.run(run())


def test_ultimos_eventos_por_stdio():
    async def run():
        async for session in _sesion_y_cliente():
            r = await session.call_tool(
                "crear_sesion",
                {"claim": CLAIM, "participantes": ["claude", "asesor"], "arbitro": None},
            )
            sid = _texto(r)["sesion_id"]
            await _debatir(session, sid)

            r = await session.call_tool("ultimos_eventos", {"sesion_id": sid, "desde_seq": 2})
            nuevos = _texto(r)
            assert [e["seq"] for e in nuevos["eventos"]] == [3, 4, 5]
            assert nuevos["ultimo_seq"] == 5

            r = await session.call_tool("ultimos_eventos", {"sesion_id": sid, "desde_seq": 5})
            assert _texto(r)["eventos"] == []

    asyncio.run(run())


def test_errores_se_reportan_sin_caer():
    async def run():
        async for session in _sesion_y_cliente():
            r = await session.call_tool("estado", {"sesion_id": "no-existe"})
            res = _texto(r)
            assert res["ok"] is False and "sesion desconocida" in res["error"]

            r = await session.call_tool("reproducir_sesion", {"claim": CLAIM, "log": "no-json"})
            assert _texto(r)["ok"] is False

    asyncio.run(run())