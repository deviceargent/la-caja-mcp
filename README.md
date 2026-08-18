# la-caja-mcp

Sistema MCP de acceso y debate sobre **La Caja** (memoria contextual).
Repo B: consumidor de La Caja (repo A). Este repo no toca el nucleo de
memoria; habla con el por API y expone la Caja a agentes.

## Que hay aca

- `src/la_caja_mcp/protocolo.py` — protocolo de debate agente-agente-humano
  (prototipo). Claims, solicitud de interferencia, rondas con deadline,
  adjudicacion humana. Determinista y replayable (event-sourcing, misma
  disciplina que La Caja).
- `tests/` — mini-falsacion de la maquina de estados.
- (pendiente) servidor FastMCP: `mcp_server.py` con un solo juego de tools
  y dos transportes (stdio local / streamable HTTP remoto), y el worker
  como ejemplo de host.

## Transportes MCP (decision de arquitectura)

- Local = `stdio` (el agente lanza el server como subproceso).
- Remoto = **streamable HTTP** (unico standard para MCP remoto, + OAuth).
- `worker/` es ejemplo de host desplegable; no hay MCP publico hosteado.

## Probar

```
$env:PYTHONPATH="src"; python -m pytest tests -q
```