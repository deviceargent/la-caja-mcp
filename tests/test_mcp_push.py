"""Discusion en vivo: push por SSE. Un agente se suscribe a
GET /caja/push?sesion_id=<id> sobre el server compartido (streamable
HTTP); cada mover() exitoso por MCP emite un evento
sesion_actualizada con el ultimo_seq."""

import asyncio
import http.client
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URL = "http://127.0.0.1:8766/mcp"
PUSH_URL = "/caja/push"
CLAIM = "la caja recupera asociaciones observadas con confianza"


def _esperar_server(timeout: float = 15.0) -> None:
    req = urllib.request.Request(
        URL,
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


def _arrancar_server():
    env = dict(os.environ)
    env["PYTHONPATH"] = os.path.join(ROOT, "src")
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "la_caja_mcp.mcp_server",
            "--transport",
            "streamable-http",
            "--host",
            "127.0.0.1",
            "--port",
            "8766",
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _sse_reader(sid: str, cola: asyncio.Queue, errores: list, stop: threading.Event, loop: asyncio.AbstractEventLoop):
    """Hilo: lee el SSE por lineas y pone {"evento", "data"} en la cola
    asyncio del loop del test (run_coroutine_threadsafe)."""
    try:
        conn = http.client.HTTPConnection("127.0.0.1", 8766, timeout=30)
        conn.request(
            "GET",
            f"{PUSH_URL}?sesion_id={sid}",
            headers={"Accept": "text/event-stream"},
        )
        resp = conn.getresponse()
        assert resp.status == 200, f"status {resp.status}"
        evento = None
        for raw in resp:
            if stop.is_set():
                break
            linea = raw.decode("utf-8", "replace").rstrip("\r\n")
            if linea.startswith("event:"):
                evento = linea[6:].strip()
            elif linea.startswith("data:"):
                asyncio.run_coroutine_threadsafe(
                    cola.put({"evento": evento, "data": json.loads(linea[5:].strip())}),
                    loop,
                ).result(timeout=5)
                evento = None
    except Exception as e:  # noqa: BLE001
        if not stop.is_set():
            errores.append(e)
    finally:
        stop.set()


def test_push_sse():
    async def run():
        proc = _arrancar_server()
        cola: asyncio.Queue = asyncio.Queue()
        errores: list = []
        stop = threading.Event()
        try:
            _esperar_server()
            async with streamable_http_client(URL) as (read, write, _):
                async with ClientSession(read, write) as ses:
                    await ses.initialize()
                    r = await ses.call_tool(
                        "crear_sesion",
                        {"claim": CLAIM, "participantes": ["alice", "bob"], "arbitro": None},
                    )
                    sid = _texto(r)["sesion_id"]

                    hilo = threading.Thread(
                        target=_sse_reader,
                        args=(sid, cola, errores, stop, asyncio.get_running_loop()),
                        daemon=True,
                    )
                    hilo.start()

                    # evento inicial "estado": snapshot con ultimo_seq 0
                    inicial = await asyncio.wait_for(cola.get(), timeout=8)
                    assert inicial["evento"] == "estado", inicial
                    assert inicial["data"]["sesion_id"] == sid
                    assert inicial["data"]["ultimo_seq"] == 0

                    r = await ses.call_tool(
                        "mover", {"sesion_id": sid, "tipo": "proponer", "actor": "alice"}
                    )
                    assert _texto(r)["ok"]

                    push = await asyncio.wait_for(cola.get(), timeout=8)
                    assert push["evento"] == "sesion_actualizada", push
                    assert push["data"]["ultimo_seq"] == 1
                    assert push["data"]["estado"] == "candidate"

                    r = await ses.call_tool(
                        "mover",
                        {
                            "sesion_id": sid,
                            "tipo": "interferir",
                            "actor": "bob",
                            "payload": '{"objecion": "sin evidencia"}',
                        },
                    )
                    assert _texto(r)["ok"]

                    push = await asyncio.wait_for(cola.get(), timeout=8)
                    assert push["evento"] == "sesion_actualizada"
                    assert push["data"]["ultimo_seq"] == 2
                    assert push["data"]["estado"] == "disputed"

                    assert errores == [], errores
        finally:
            stop.set()
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)

    asyncio.run(run())