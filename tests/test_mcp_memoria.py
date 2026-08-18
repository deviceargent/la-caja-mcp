"""Integracion: las tools de memoria de La Caja (repo A) via cliente MCP
real por stdio. Requiere el paquete la-caja instalado."""

import asyncio
import json
import os
import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

la_caja = pytest.importorskip("la_caja")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _texto(resultado):
    for bloque in resultado.content:
        if bloque.type == "text":
            return json.loads(bloque.text)
    raise AssertionError(f"sin contenido de texto: {resultado}")


async def _cliente():
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


def test_memoria_ingesta_consulta_y_primado():
    async def run():
        async for session in _cliente():
            r = await session.call_tool("procesar_consulta", {"texto": "el sol tiene masa"})
            ingesta = _texto(r)
            assert ingesta["ok"], ingesta

            r = await session.call_tool("consultar", {"a": "sol", "b": "masa"})
            assert _texto(r)["confianza"] == 1.0

            r = await session.call_tool("contexto_primado", {"termino": "sol", "presupuesto": 5})
            primado = _texto(r)
            assert primado["ok"] and "masa" in primado["primado"]

            r = await session.call_tool("stats", {})
            stats = _texto(r)
            assert stats["ok"] and stats["terminos"] >= 2

    asyncio.run(run())


def test_memoria_historial_expone_la_traza_dormida():
    async def run():
        async for session in _cliente():
            r = await session.call_tool("procesar_consulta", {"texto": "el sol tiene masa"})
            assert _texto(r)["ok"]

            r = await session.call_tool("historial", {"termino": "sol"})
            h = _texto(r)
            assert h["ok"] and h["historial"] == [], "termino sin olvido: sin traza"


def test_memoria_coocurrencias_separadas_no_inventan_puentes():
    async def run():
        async for session in _cliente():
            for a, b in [("sol", "estrella"), ("estrella", "gigante")]:
                r = await session.call_tool("declarar_relacion", {"a": a, "b": b})
                assert _texto(r)["ok"]

            r = await session.call_tool("consultar", {"a": "sol", "b": "estrella"})
            assert _texto(r)["confianza"] == 1.0

            r = await session.call_tool("consultar", {"a": "sol", "b": "gigante"})
            assert _texto(r)["confianza"] == 0.0

    asyncio.run(run())