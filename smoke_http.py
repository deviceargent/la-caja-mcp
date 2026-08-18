"""Smoke test del transporte streamable HTTP: arranca el server como
subproceso y un cliente MCP remoto procesa el debate completo."""

import asyncio
import json
import os
import subprocess
import sys
import time
import urllib.request

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

ROOT = os.path.dirname(os.path.abspath(__file__))
URL = "http://127.0.0.1:8765/mcp"


def _esperar_server(timeout: float = 15.0) -> None:
    req = urllib.request.Request(
        "http://127.0.0.1:8765/mcp",
        headers={"Accept": "application/json, text/event-stream"},
    )
    fin = time.time() + timeout
    while time.time() < fin:
        try:
            urllib.request.urlopen(req, timeout=1)
            return
        except urllib.error.HTTPError:
            return
        except Exception:
            time.sleep(0.3)
    raise RuntimeError("el server no arranco a tiempo")


def _texto(resultado):
    for bloque in resultado.content:
        if bloque.type == "text":
            return json.loads(bloque.text)
    raise AssertionError(f"sin contenido de texto: {resultado}")


async def main() -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.path.join(ROOT, "src")
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "la_caja_mcp.mcp_server",
            "--transport",
            "streamable-http",
            "--host",
            "127.0.0.1",
            "--port",
            "8765",
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _esperar_server()
        async with streamable_http_client(URL) as (read, write, get_session_id):
            async with ClientSession(read, write) as session:
                await session.initialize()

                r = await session.call_tool(
                    "crear_sesion",
                    {
                        "claim": "la caja recupera asociaciones observadas con confianza",
                        "participantes": ["claude", "asesor", "humano"],
                        "arbitro": "humano",
                    },
                )
                crear = _texto(r)
                assert crear["ok"], crear
                sid = crear["sesion_id"]

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

                r = await session.call_tool("ultimos_eventos", {"sesion_id": sid, "desde_seq": 5})
                nuevos = _texto(r)
                assert nuevos["eventos"] == [], nuevos

                log = json.dumps(estado["log"], ensure_ascii=False)
                r = await session.call_tool("reproducir_sesion", {"claim": "la caja recupera asociaciones observadas con confianza", "log": log})
                replay = _texto(r)
                assert replay["ok"] and replay["estado"]["estado"] == "consensus", replay

                print("replay remoto:", replay["estado"]["estado"])
                print("SMOKE STREAMABLE HTTP OK")
    finally:
        proc.terminate()
        proc.wait(timeout=10)


if __name__ == "__main__":
    asyncio.run(main())
