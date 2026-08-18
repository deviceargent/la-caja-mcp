# la-caja-mcp

Sistema MCP de acceso y debate sobre **La Caja** (memoria contextual).
Repo B: consumidor de La Caja (repo A). Este repo no toca el nucleo de
memoria; habla con el por API y expone la Caja a agentes.

## Que hay aca

- `src/la_caja_mcp/protocolo.py` — protocolo de debate agente-agente-humano.
  Claims, solicitud de interferencia, rondas con deadline, adjudicacion
  humana. Determinista y replayable (event-sourcing, misma disciplina que
  La Caja).
- `src/la_caja_mcp/mcp_server.py` — servidor MCP con un solo juego de tools
  y dos transportes (stdio local / streamable HTTP remoto).
- `tests/` — mini-falsacion de la maquina de estados + integracion con
  cliente MCP real por stdio.
- `demo_debate.py` — demo del debate que cierra en consensus.
- `smoke_http.py` — smoke test del transporte streamable HTTP (arranca el
  server y lo ejercita un cliente remoto).

## Servidor MCP

Un juego de tools, dos transportes:

```
# local (stdio): lo lanza el agente como subproceso
la-caja-mcp --transport stdio

# remoto (streamable HTTP): unico standard para MCP sobre red
la-caja-mcp --transport streamable-http --host 127.0.0.1 --port 8000
```

Tools: `crear_sesion`, `mover`, `estado`, `ultimos_eventos`,
`reproducir_sesion`. El payload de `mover` es JSON (ver docstring del
modulo). `app = mcp.http_app(transport="streamable-http")` queda listo
para que un host (p. ej. worker de Cloudflare) lo sirva con OAuth.

## Transportes MCP (decision de arquitectura)

- Local = `stdio` (el agente lanza el server como subproceso).
- Remoto = **streamable HTTP** (unico standard para MCP remoto, + OAuth).
- `worker/` es ejemplo de host desplegable; no hay MCP publico hosteado.

## Probar

```
$env:PYTHONPATH="src"; python -m pytest tests -q
```