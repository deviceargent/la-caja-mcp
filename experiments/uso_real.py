"""Caso de uso real (pre-registrado en falsacion.md de La Caja, 19/8/2026).

Escenario de prueba en conjunto: dos agentes MCP (claude y asesor)
compartiendo la memoria de La Caja via `la-caja-mcp` por streamable HTTP
en localhost, con la memoria persistida en SQLite (--caja-db).

Metricas pre-registradas (se reportan todas, sin cherry-pick):
- ok_memoria: la ingesta de claude es visible para asesor.
- ok_debate: la sesion llega a consensus por el protocolo.
- ok_replay: reproducir_sesion del log da el mismo estado final.
- ok_push: un suscriptor SSE en /caja/push recibe al menos un evento.
- tiempos: ingesta y debate (parlamento de latencia, no criterio).
Veredicto FALSA (falla de integracion) si cualquiera de los ok_* es False.
"""

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

ROOT = os.path.dirname(os.path.abspath(__file__))
PORT = 8765
URL = f"http://127.0.0.1:{PORT}/mcp"

INGESTA = [
    "el servidor central se migra a postgres la proxima semana",
    "postgres va en el servidor central con 64GB de ram",
    "la migracion a postgres cierra la ventana de escritura el sabado",
    "el backup nocturno pasa despues de la ventana de escritura",
]

CLAIM = "la migracion a postgres del servidor central es segura el sabado"

CLAIM_INTERFERENCIA = "la ventana de escritura del sabado no afecta al backup nocturno"


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


def _suscribirse_sse(sesion_id: str, eventos: list):
    import threading

    import urllib.request

    def _leer():
        try:
            r = urllib.request.urlopen(
                f"http://127.0.0.1:{PORT}/caja/push?sesion_id={sesion_id}",
                timeout=60,
            )
            for linea in r:
                linea = linea.decode("utf-8", "replace").strip()
                if linea.startswith("event:") or linea.startswith("data:"):
                    eventos.append(linea)
        except Exception:
            pass

    t = threading.Thread(target=_leer, daemon=True)
    t.start()
    return t


async def main() -> None:
    tmpdir = tempfile.mkdtemp(prefix="uso_real_")
    db = os.path.join(tmpdir, "caja.db")
    env = dict(os.environ)
    env["PYTHONPATH"] = os.path.join(ROOT, "..", "src")
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
            str(PORT),
            "--caja-db",
            db,
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _esperar_server()

        async with streamable_http_client(URL) as (read_c, write_c, _):
            async with ClientSession(read_c, write_c) as claude:
                await claude.initialize()
                async with streamable_http_client(URL) as (read_a, write_a, _):
                    async with ClientSession(read_a, write_a) as asesor:
                        await asesor.initialize()

                        t0 = time.time()
                        for texto in INGESTA:
                            r = await claude.call_tool("procesar_consulta", {"texto": texto})
                            assert _texto(r)["ok"], _texto(r)
                        t_ingesta = time.time() - t0

                        r = await claude.call_tool("stats", {})
                        stats_claude = _texto(r)
                        r = await asesor.call_tool("stats", {})
                        stats_asesor = _texto(r)
                        ok_memoria = (
                            stats_claude["ok"]
                            and stats_asesor["ok"]
                            and stats_asesor["terminos"] > 0
                            and stats_asesor["terminos"] == stats_claude["terminos"]
                        )

                        r = await asesor.call_tool("contexto_primado", {"termino": "postgres", "presupuesto": 10})
                        primado = _texto(r)
                        tiene_termino = any(
                            t in primado.get("primado", []) for t in ("servidor", "central", "sabado", "ventana")
                        )
                        ok_memoria = ok_memoria and primado["ok"] and tiene_termino

                        r = await claude.call_tool(
                            "crear_sesion",
                            {
                                "claim": CLAIM,
                                "participantes": ["claude", "asesor"],
                                "arbitro": "claude",
                                "limite_turnos": 2,
                            },
                        )
                        sesion_id = _texto(r)["sesion_id"]

                        eventos_sse: list[str] = []
                        hilo = _suscribirse_sse(sesion_id, eventos_sse)
                        time.sleep(0.5)

                        t0 = time.time()
                        for tipo, actor, payload in [
                            ("proponer", "claude", "{}"),
                            ("interferir", "asesor", '{"objecion": "la ventana de escritura el sabado corta el backup"}'),
                            ("responder", "claude", '{"defensa": "el backup corre despues de la ventana, segun la memoria"}'),
                            ("condiciones", "asesor", '{"lista": ["postgres en servidor central", "backup nocturno despues de la ventana"]}'),
                            ("aceptar", "asesor", "{}"),
                        ]:
                            r = await claude.call_tool("mover", {"sesion_id": sesion_id, "tipo": tipo, "actor": actor, "payload": payload})
                            assert _texto(r)["ok"], _texto(r)
                        t_debate = time.time() - t0

                        r = await claude.call_tool("estado", {"sesion_id": sesion_id})
                        estado = _texto(r)
                        ok_debate = estado["ok"] and estado["estado"]["estado"] == "consensus"

                        log = json.dumps(estado["log"], ensure_ascii=False)
                        r = await claude.call_tool("reproducir_sesion", {"claim": CLAIM, "log": log})
                        replay = _texto(r)
                        ok_replay = (
                            replay["ok"]
                            and replay["estado"]["estado"] == "consensus"
                            and replay["n_eventos"] == len(estado["log"])
                        )

                        time.sleep(1.0)
                        ok_push = any("event:" in e or "data:" in e for e in eventos_sse)
                        hilo.join(timeout=2)

                        # Segundo escenario: solicitud de interferencia completa
                        # con deadline. limite_turnos=1: una charla del autor
                        # (manifestar, no responder/escalar) consume el deadline;
                        # vence -> escalar -> unresolved -> el humano adjudica.
                        r = await claude.call_tool(
                            "crear_sesion",
                            {
                                "claim": CLAIM_INTERFERENCIA,
                                "participantes": ["claude", "asesor", "humano"],
                                "arbitro": "humano",
                                "limite_turnos": 1,
                            },
                        )
                        sid2 = _texto(r)["sesion_id"]

                        eventos_sse2: list[str] = []
                        hilo2 = _suscribirse_sse(sid2, eventos_sse2)
                        time.sleep(0.5)

                        for tipo, actor, payload in [
                            ("proponer", "claude", "{}"),
                            ("interferir", "asesor", '{"objecion": "la ventana de escritura corta la ventana del backup"}'),
                            ("manifestar", "claude", '{"texto": "el plan mantiene el backup nocturno"}'),
                        ]:
                            r = await claude.call_tool("mover", {"sesion_id": sid2, "tipo": tipo, "actor": actor, "payload": payload})
                            assert _texto(r)["ok"], _texto(r)

                        r = await claude.call_tool("estado", {"sesion_id": sid2})
                        estado2 = _texto(r)
                        # tras manifestar del autor en disputed con limite 1,
                        # vence_en_turnos debe haber bajado a 0 -> escalar valido
                        r = await claude.call_tool("mover", {"sesion_id": sid2, "tipo": "escalar", "actor": "claude", "payload": "{}"})
                        escalar = _texto(r)
                        ok_escalar = escalar["ok"] and escalar["estado"]["estado"] == "unresolved"

                        r = await claude.call_tool("mover", {"sesion_id": sid2, "tipo": "adjudicar", "actor": "humano", "payload": '{"decision": "consensus"}'})
                        adjudicar = _texto(r)
                        ok_adjudicar = adjudicar["ok"] and adjudicar["estado"]["estado"] == "consensus"

                        r = await claude.call_tool("estado", {"sesion_id": sid2})
                        estado_final2 = _texto(r)
                        log2 = json.dumps(estado_final2["log"], ensure_ascii=False)
                        r = await claude.call_tool("reproducir_sesion", {"claim": CLAIM_INTERFERENCIA, "log": log2})
                        replay2 = _texto(r)
                        ok_replay2 = replay2["ok"] and replay2["estado"]["estado"] == "consensus"

                        time.sleep(0.5)
                        ok_push2 = any("event:" in e or "data:" in e for e in eventos_sse2)
                        hilo2.join(timeout=2)

                        veredicto_interf = "FALSA" if not (
                            ok_escalar and ok_adjudicar and ok_replay2 and ok_push2
                        ) else "OK"

                        print(json.dumps({
                            "ok_memoria": ok_memoria,
                            "ok_debate": ok_debate,
                            "ok_replay": ok_replay,
                            "ok_push": ok_push,
                            "solicitud_interferencia": {
                                "ok_escalar": ok_escalar,
                                "ok_adjudicar": ok_adjudicar,
                                "ok_replay": ok_replay2,
                                "ok_push": ok_push2,
                                "vence_en_turnos_tras_manifestar": estado2["estado"].get("vence_en_turnos"),
                                "veredicto": veredicto_interf,
                            },
                            "tiempos": {"ingesta": round(t_ingesta, 2), "debate": round(t_debate, 2)},
                            "stats": {"claude": stats_claude["terminos"], "asesor": stats_asesor["terminos"]},
                            "primado_postgres": primado.get("primado", [])[:6],
                            "n_sse": len(eventos_sse),
                            "veredicto": "FALSA" if not (ok_memoria and ok_debate and ok_replay and ok_push) else "OK",
                        }, ensure_ascii=False))
    finally:
        proc.terminate()
        proc.wait(timeout=10)


if __name__ == "__main__":
    asyncio.run(main())