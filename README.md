# la-caja-mcp

Sistema MCP de acceso y debate sobre **La Caja** (memoria contextual).
Repo B: consumidor de La Caja (repo A). Este repo no toca el nucleo de
memoria; habla con el por API y expone la Caja a agentes.

## Que hay aca

- `src/la_caja_mcp/protocolo.py` — protocolo de debate agente-agente-humano.
  Claims, solicitud de interferencia, rondas con deadline en turnos,
  escalada y adjudicacion humana. Determinista y replayable
  (event-sourcing, misma disciplina que La Caja). La maquina de estados
  es un contrato: en `disputed` el autor solo puede responder o escalar;
  `unresolved` (deadlock) es el UNICO terminal que el humano puede
  adjudicar.
- `src/la_caja_mcp/mcp_server.py` — servidor MCP: tools del debate + tools
  de memoria de La Caja (repo A, consumido por API), un solo juego de
  tools y dos transportes (stdio local / streamable HTTP remoto).
- `tests/` — falsacion de la maquina de estados + integracion con cliente
  MCP real por stdio (debate y memoria) + push SSE multiagente (31 tests).
- `experiments/uso_real.py` — caso de uso real: dos agentes LLM como
  clientes MCP (memoria compartida, debate, replay, push).
- `experiments/interrupcion_etapas.py` — la base del protocolo: un agente
  al medio del razonamiento acepta ser interrumpido y cede dentro de la
  ronda.
- `worker/` — host ASGI portable (uvicorn + Dockerfile) para el MCP remoto.

## Validado con LLM reales (OpenRouter, gpt-4o-mini, por streamable HTTP)

| Validación | Resultado |
|---|---|
| Caso de uso real (2 agentes MCP, memoria compartida) | **OK** — consensus, replay, push |
| Solicitud de interferencia completa (deadline → escalar → humano) | **OK** |
| **Interrupción al medio del razonamiento** | **OK** — `proponer → manifestar → interferir → responder → aceptar` |

La base del protocolo funciona: el autor expone su razonamiento por
etapas con `manifestar` (el medio de interrupción), consulta el estado
entre etapas, el interferente solicita `interferir` al medio, y el
interrumpido cede respondiendo dentro de la ronda (vence_en_turnos
intacto). Detalle del diseño y sus límites en el writeup de La Caja
(`experiments/writeup.md`, repo A).

## Instalación

Paquete de Python estándar (`la-caja-mcp`), igual que su dependencia
`la-caja` (repo A):

```
# Directo del repositorio (funciona hoy)
pip install git+https://github.com/deviceargent/la-caja-mcp.git

# Publicado (PyPI): una vez publicado
pip install la-caja-mcp

# Desarrollo local
pip install .
```

Instala el ejecutable `la-caja-mcp` y las dependencias (`fastmcp`,
`la-caja`). El worker remoto necesita el extra de hosting:

```
pip install "la-caja-mcp[host]"    # o  pip install .[host]  en el repo
```

## Servidor MCP

Un juego de tools, dos transportes:

```
# local (stdio): lo lanza el agente como subproceso
la-caja-mcp --transport stdio

# remoto (streamable HTTP): unico standard para MCP sobre red
la-caja-mcp --transport streamable-http --host 127.0.0.1 --port 8000
```

Debate: `crear_sesion`, `mover` (payload JSON), `estado`,
`ultimos_eventos`, `reproducir_sesion`.
Memoria (requiere `pip install la-caja`; repo A): `procesar_consulta`,
`declarar_relacion`, `consultar`, `contexto_primado`, `historial`
(traza dormida, capa inerte), `stats`.

La memoria es persistente con `--caja-db <ruta>` (SQLite, event-sourcing
de La Caja) o `LA_CAJA_DB`; sin eso, en memoria pura.

## Discusion en vivo (push)

En streamable HTTP el server expone ademas un endpoint SSE:

```
GET /caja/push?sesion_id=<id>
```

Emite un evento `estado` (snapshot: `ultimo_seq` + `estado`) al conectar
y luego un `sesion_actualizada` por cada `mover()` exitoso. Un agente se
suscribe con una conexion HTTP aparte (cualquier stack) y usa
`ultimos_eventos` para traer el detalle. Requiere server compartido: en
stdio cada agente tiene su propio proceso, ahi la vivacidad es por
sondeo con `ultimos_eventos`.

## Transportes MCP (decision de arquitectura)

- Local = `stdio` (el agente lanza el server como subproceso).
- Remoto = **streamable HTTP** (unico standard para MCP remoto, + OAuth).
- `worker/` es ejemplo de host desplegable (VPS/Docker); no hay MCP
  publico hosteado.

## Probar

```
$env:PYTHONPATH="src"; python -m pytest tests -q
python experiments/uso_real.py                    # requiere OPENAI_API_KEY
python experiments/interrupcion_etapas.py         # requiere OPENAI_API_KEY
```

## Licencia

MIT — ver [LICENSE](LICENSE).