"""Interrupcion entre agentes al medio del razonamiento (pre-registrado
en falsacion.md de La Caja, 19/8/2026).

La base del protocolo, en la practica: un agente, al medio del
razonamiento, debe ACEPTAR ser interrumpido por otro agente. Los agentes
con modo texto exponen el razonamiento por etapas de conclusion. Este
harness lo ejercita con dos agentes LLM reales (OpenRouter, gpt-4o-mini)
como clientes MCP de la-caja-mcp por streamable HTTP:

- El AUTOR razona por etapas: en cada etapa produce una conclusion
  parcial y la EXPONE con `manifestar` (ese es el medio de interrupcion:
  el log compartido + ultimos_eventos). Entre etapa y etapa CONSULTA el
  estado: si alguien lo interrumpio, se detiene y cede.
- El INTERFERENTE observa las etapas (ultimos_eventos), y al medio del
  razonamiento solicita la interrupcion con `interferir` (ronda con
  deadline).
- El autor detecta `disputed` en la frontera de la siguiente etapa,
  ACEPTA la interrupcion y responde dentro de la ronda (no escala, no
  ignora). El interferente acepta la defensa -> consensus.

Metricas pre-registradas (se reportan todas, sin cherry-pick):
- ok_etapas: el autor expuso >= 1 etapa (manifestar) antes de ser
  interrumpido (estaba razonando al medio).
- ok_interrupcion: el interferente solicito interferir mientras el autor
  aun estaba en candidate (razonamiento en curso, no terminado).
- ok_cedio: el autor detecto disputed en una frontera de etapa, dejo de
  razonar y respondio dentro de la ronda (vence_en_turnos > 0 al
  detectar; no dejo vencer el deadline, no escalo).
- ok_consensus: la sesion llega a consensus.
- ok_replay: reproducir_sesion(log) da el mismo estado final.

Veredicto FALSA si cualquiera de los ok_* es False (falla de la base del
protocolo). Las metricas de la maquina de estados ya estan cubiertas por
los 31 tests; aqui lo que se mide es el bucle de etapas con LLM real.
"""

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

from openai import OpenAI
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

ROOT = os.path.dirname(os.path.abspath(__file__))
PORT = 8766
URL = f"http://127.0.0.1:{PORT}/mcp"

BASE_URL = os.environ.get("EVAL_BASE_URL", "https://openrouter.ai/api/v1")
MODELO = os.environ.get("EVAL_MODELO", "openai/gpt-4o-mini")
_cliente = OpenAI(api_key=os.environ["OPENAI_API_KEY"], base_url=BASE_URL, max_retries=2, timeout=30)

CLAIM = "la migracion a postgres debe ejecutarse el sabado por la manana, antes de la ventana de cierre"
MAX_ETAPAS = 5
SLEEP_ETAPA = 0.3
POLL = 0.2


def _llm(prompt: str) -> str:
    r = _cliente.chat.completions.create(
        model=MODELO,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5,
        max_tokens=90,
    )
    return (r.choices[0].message.content or "").strip() or "(sin texto)"


def _esperar_server(timeout: float = 15.0) -> None:
    req = urllib.request.Request(URL, headers={"Accept": "application/json, text/event-stream"})
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


async def _rol_autor(ses, sid: str, registro: dict) -> None:
    r = await ses.call_tool(
        "mover",
        {"sesion_id": sid, "tipo": "proponer", "actor": "autor", "payload": "{}"},
    )
    assert _texto(r)["ok"], _texto(r)

    etapas_expuestas = 0
    vence_al_detectar = None
    defensa = None
    for etapa in range(1, MAX_ETAPAS + 1):
        r = await ses.call_tool("estado", {"sesion_id": sid})
        data = _texto(r)
        st = data["estado"]
        if st["estado"] == "disputed":
            # Acepta la interrupcion en la frontera: deja de razonar y
            # responde dentro de la ronda. No escala, no se hace el sordo.
            vence_al_detectar = st["vence_en_turnos"]
            objecion = next(
                (e.get("objecion", "") for e in data["log"] if e["tipo"] == "interferir"),
                "",
            )
            defensa = _llm(
                f"Sos el autor del claim: {CLAIM}. Te objetaron: {objecion}. "
                "Escribi en una sola frase tu defensa."
            )
            r = await ses.call_tool(
                "mover",
                {"sesion_id": sid, "tipo": "responder", "actor": "autor",
                 "payload": json.dumps({"defensa": defensa})},
            )
            assert _texto(r)["ok"], _texto(r)
            registro["cedio"] = True
            break
        # Etapa de razonamiento: produce la conclusion parcial y la expone.
        concl = _llm(
            f"Sos el autor del claim: {CLAIM}. Tu razonamiento avanza por etapas. "
            f"Etapa {etapa}: escribi en una sola frase la proxima conclusion parcial "
            "de tu razonamiento que sustenta el claim."
        )
        r = await ses.call_tool(
            "mover",
            {"sesion_id": sid, "tipo": "manifestar", "actor": "autor",
             "payload": json.dumps({"texto": concl})},
        )
        assert _texto(r)["ok"], _texto(r)
        etapas_expuestas += 1
        registro["etapas"].append(concl)
        await asyncio.sleep(SLEEP_ETAPA)

    registro["etapas_expuestas"] = etapas_expuestas
    registro["vence_al_detectar"] = vence_al_detectar
    registro["defensa"] = defensa


async def _rol_interferente(ses, sid: str, registro: dict) -> None:
    ultimo = 0
    # Espera la primera etapa expuesta: el medio de interrupcion.
    while True:
        r = await ses.call_tool("ultimos_eventos", {"sesion_id": sid, "desde_seq": ultimo})
        data = _texto(r)
        ultimo = data["ultimo_seq"]
        if any(e["tipo"] == "manifestar" for e in data["eventos"]):
            break
        await asyncio.sleep(POLL)

    objecion = _llm(
        f"Sos el critico del claim: {CLAIM}. Escribi en una sola frase una objecion razonable."
    )
    registro["objecion"] = objecion
    r = await ses.call_tool(
        "mover",
        {"sesion_id": sid, "tipo": "interferir", "actor": "interferente",
         "payload": json.dumps({"objecion": objecion})},
    )
    assert _texto(r)["ok"], _texto(r)
    registro["interfirio"] = True

    # Espera la defensa del autor y la acepta -> consensus.
    ultimo = 0
    while True:
        r = await ses.call_tool("ultimos_eventos", {"sesion_id": sid, "desde_seq": ultimo})
        data = _texto(r)
        ultimo = data["ultimo_seq"]
        if any(e["tipo"] == "responder" for e in data["eventos"]):
            break
        await asyncio.sleep(POLL)
    r = await ses.call_tool("mover", {"sesion_id": sid, "tipo": "aceptar", "actor": "interferente", "payload": "{}"})
    assert _texto(r)["ok"], _texto(r)
    registro["acepto"] = True


async def main() -> None:
    tmpdir = tempfile.mkdtemp(prefix="interrupcion_")
    db = os.path.join(tmpdir, "caja.db")
    env = dict(os.environ)
    env["PYTHONPATH"] = os.path.join(ROOT, "..", "src")
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "la_caja_mcp.mcp_server",
            "--transport", "streamable-http",
            "--host", "127.0.0.1",
            "--port", str(PORT),
            "--caja-db", db,
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _esperar_server()

        async with streamable_http_client(URL) as (rc, wc, _):
            async with ClientSession(rc, wc) as autor:
                await autor.initialize()
                async with streamable_http_client(URL) as (ri, wi, _):
                    async with ClientSession(ri, wi) as interferente:
                        await interferente.initialize()

                        r = await autor.call_tool(
                            "crear_sesion",
                            {"claim": CLAIM, "participantes": ["autor", "interferente"],
                             "arbitro": None, "limite_turnos": 2},
                        )
                        sid = _texto(r)["sesion_id"]

                        registro = {"etapas": [], "cedio": False, "interfirio": False, "acepto": False}
                        await asyncio.gather(
                            _rol_autor(autor, sid, registro),
                            _rol_interferente(interferente, sid, registro),
                        )

                        r = await autor.call_tool("estado", {"sesion_id": sid})
                        estado = _texto(r)
                        log = estado["log"]
                        secuencia = [e["tipo"] for e in log]

                        r = await autor.call_tool(
                            "reproducir_sesion",
                            {"claim": CLAIM, "log": json.dumps(log, ensure_ascii=False)},
                        )
                        replay = _texto(r)

                        ok_etapas = registro["etapas_expuestas"] >= 1
                        # ok_interrupcion: el interferir ocurrio con el autor en
                        # candidate (razonamiento en curso). Lo verificamos por el
                        # log: no hay responder ni escalar antes del interferir.
                        idx_interf = next(i for i, t in enumerate(secuencia) if t == "interferir")
                        antes = secuencia[:idx_interf]
                        ok_interrupcion = (
                            registro["interfirio"]
                            and "responder" not in antes
                            and "escalar" not in antes
                        )
                        ok_cedio = (
                            registro["cedio"]
                            and registro["vence_al_detectar"] is not None
                            and registro["vence_al_detectar"] > 0
                        )
                        ok_consensus = estado["ok"] and estado["estado"]["estado"] == "consensus"
                        ok_replay = (
                            replay["ok"]
                            and replay["estado"]["estado"] == "consensus"
                            and replay["n_eventos"] == len(log)
                        )

                        print(json.dumps({
                            "ok_etapas": ok_etapas,
                            "ok_interrupcion": ok_interrupcion,
                            "ok_cedio": ok_cedio,
                            "ok_consensus": ok_consensus,
                            "ok_replay": ok_replay,
                            "veredicto": "FALSA" if not (
                                ok_etapas and ok_interrupcion and ok_cedio and ok_consensus and ok_replay
                            ) else "OK",
                            "etapas_expuestas": registro["etapas_expuestas"],
                            "vence_al_detectar": registro["vence_al_detectar"],
                            "secuencia": secuencia,
                            "etapas_autor": registro["etapas"],
                            "objecion": registro["objecion"],
                            "defensa": registro["defensa"],
                        }, ensure_ascii=False))
    finally:
        proc.terminate()
        proc.wait(timeout=10)


if __name__ == "__main__":
    asyncio.run(main())