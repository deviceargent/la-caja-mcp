# la-caja-mcp

Sistema MCP de acceso y debate sobre **La Caja** (memoria contextual).
Repo B: consumidor de La Caja (repo A). Este repo no toca el nucleo de
memoria; habla con el por API y expone la Caja a agentes.

## Que hay aca

- `src/la_caja_mcp/protocolo.py` — protocolo de debate agente-agente-humano.
  Claims, solicitud de interferencia, rondas con deadline, adjudicacion
  humana. Determinista y replayable (event-sourcing, misma disciplina que
  La Caja).
- `src/la_caja_mcp/mcp_server.py` — servidor MCP: tools del debate + tools
  de memoria de La Caja (repo A, consumido por API), un solo juego de
  tools y dos transportes (stdio local / streamable HTTP remoto).
- `tests/` — mini-falsacion de la maquina de estados + integracion con
  cliente MCP real por stdio (debate y memoria) + push SSE multiagente.
- `demo_debate.py` — demo del debate que cierra en consensus.
- `smoke_http.py` — smoke test del transporte streamable HTTP.
- `worker/` — host ASGI portable (uvicorn + Dockerfile) para el MCP remoto.

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
`declarar_relacion`, `consultar`, `contexto_primado`, `stats`.

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
```