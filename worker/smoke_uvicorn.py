"""Smoke del worker: debate completo contra el host uvicorn (el mismo app
del repo, servido como ASGI), via un cliente MCP remoto."""

import asyncio
import json
import os
import socket
import subprocess
import sys
import time

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URL = "http://127.0.0.1:8766/mcp"
CLAIM = "la caja recupera asociaciones observadas con confianza"


def _esperar_puerto(host: str, port: int, timeout: float = 15.0) -> None:
    fin = time.time() + timeout
    while time.time() < fin:
        try:
            with socket.create_connection((host, port), timeout=1):
                return
        except OSError:
            time.sleep(0.3)
    raise RuntimeError("el host uvicorn no escucha a tiempo")


def _texto(resultado):
    for bloque in resultado.content:
        if bloque.type == "text":
            return json.loads(bloque.text)
    raise AssertionError(f"sin contenido de texto: {resultado}")


async def main() -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.path.join(ROOT, "src")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "la_caja_mcp.mcp_server:app", "--host", "127.0.0.1", "--port", "8766"],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        _esperar_puerto("127.0.0.1", 8766)
        async with streamable_http_client(URL) as (read, write, get_session_id):
            async with ClientSession(read, write) as session:
                await session.initialize()
                r = await session.call_tool(
                    "crear_sesion",
                    {"claim": CLAIM, "participantes": ["claude", "asesor", "humano"], "arbitro": "humano"},
                )
                sid = _texto(r)["sesion_id"]

                for tipo, actor, payload in [
                    ("proponer", "claude", "{}"),
                    ("interferir", "asesor", '{"objecion": "presupuesto"}'),
                    ("responder", "claude", '{"defensa": "subimos a 50"}'),
                    ("condiciones", "asesor", '{"lista": ["presupuesto 50"]}'),
                    ("aceptar", "asesor", "{}"),
                ]:
                    r = await session.call_tool("mover", {"sesion_id": sid, "tipo": tipo, "actor": actor, "payload": payload})
                    assert _texto(r)["ok"], _texto(r)

                r = await session.call_tool("estado", {"sesion_id": sid})
                estado = _texto(r)
                assert estado["estado"]["estado"] == "consensus", estado

                log = json.dumps(estado["log"], ensure_ascii=False)
                r = await session.call_tool("reproducir_sesion", {"claim": CLAIM, "log": log})
                replay = _texto(r)
                assert replay["ok"] and replay["estado"]["estado"] == "consensus", replay

                print("worker uvicorn -> debate en consensus, replay OK")
                print("SMOKE WORKER UVICORN OK")
    finally:
        proc.terminate()
        proc.wait(timeout=10)


if __name__ == "__main__":
    asyncio.run(main())