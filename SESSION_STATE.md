# la-caja-mcp — Session State (handoff)

## Estado operativo (importante)

- **Uso público: se depreca.** El README y la documentación no deben
  prometer soporte público; el empaquetado/PyPI del repo B queda en
  segundo plano y no es urgente.
- **Uso privado (este proyecto maratónico): sigue en operación.** El
  server MCP, las tools, el debate y el push SSE son la vía de acceso a
  La Caja (repo A) para agentes. NO se da de baja; sigue siendo la
  interfaz activa mientras dure el proyecto.
- Regla: nada de retirar funcionalidad o romper compatibilidad hasta
  que se decida la baja definitiva. El historial completo (repo A
  `SESSION_STATE.md`) registra todo lo posterior a `e0c5fd6`.

## Estado actual

- main `823f076` — **29/29 tests verdes**
  (`$env:PYTHONPATH="src"; python -m pytest tests -q`).
- Remoto: `https://github.com/deviceargent/la-caja-mcp`; identidad
  `deviceargent` / `deviceargent@users.noreply.github.com`.

## Qué está implementado (todo posterior al cutoff de Claude, e0c5fd6)

- `3d75317` prototipo del protocolo de debate agente-agente-humano
  (claims, interferencia, rondas con deadline, adjudicación; determinista
  y replayable).
- `03ac82f` un server FastMCP, dos transportes: **stdio** (local) y
  **streamable HTTP** (remoto).
- `1d802d7` worker: host ASGI portable (uvicorn + Dockerfile) en `worker/`.
- `fe82014` tools de memoria de La Caja (repo A) como consumidor vía API:
  `procesar_consulta`, `declarar_relacion`, `consultar`, `contexto_primado`,
  `stats`. Memoria persistente con `--caja-db <ruta>` o `LA_CAJA_DB`.
- `3e816db` MCP de deliberación original (asíncrono + worker Cloudflare)
  movido a `legacy/` (mcp y mcp-cloudflare, con sus `SESSION_STATE.md`).
- `38f4fe3` CI para la suite completa (29 tests).
- `2a3bb0c` **discusión en vivo por SSE**: endpoint `GET /caja/push?sesion_id=<id>`
  sobre streamable HTTP; emite `estado` al conectar y `sesion_actualizada`
  por cada `mover()` exitoso.
- `e3be2de` licencia MIT (2026 Miguel Okstein).
- `871ab8a` tool **`historial(termino)`**: traza dormida de la-caja 0.7
  (partners olvidados: fuerza pico, último evento, capturas). Es la última
  tool registrada.
- `4970672` empaquetado real: pyproject completo, workflow PyPI
  `.github/workflows/pypi.yml` (trusted publishing), README con
  instalación explicada (PyPI / git+ / local), wheel verificado
  (`la-caja-mcp-0.1.0`).
- `c0040e5` / `823f076` gitignore: build/, *.egg-info/ (con corrección de
  líneas concatenadas).

## Tools MCP actuales

- Debate: `crear_sesion`, `mover`, `estado`, `ultimos_eventos`,
  `reproducir_sesion`.
- Memoria: `procesar_consulta`, `declarar_relacion`, `consultar`,
  `contexto_primado`, `historial`, `stats`.
- Archivos: `src/la_caja_mcp/protocolo.py`, `src/la_caja_mcp/mcp_server.py`,
  `tests/`, `demo_debate.py`, `smoke_http.py`, `worker/`.

## Cómo operar (uso privado)

```
# local (stdio): lo lanza el agente como subproceso
la-caja-mcp --transport stdio --caja-db memoria.db

# remoto (streamable HTTP): worker compartido para multiagente
la-caja-mcp --transport streamable-http --host 127.0.0.1 --port 8000 --caja-db memoria.db
```

- En stdio cada agente tiene su proceso (vivacidad por sondeo con
  `ultimos_eventos`); en streamable HTTP hay push SSE y estado compartido.
- `worker/` es ejemplo de host desplegable (VPS/Docker); no hay MCP
  público hosteado.

## Deliberadamente NO hecho todavía

- **Caso de uso real (siguiente paso del proyecto):** dos agentes
  consumiendo la memoria y el protocolo de debate por MCP contra un
  worker compartido; objetivo medible si el primado cambia cómo un agente
  interfiere y si el consenso emerge más rápido con memoria compartida.
- Publicación a PyPI de B (bloqueada por la decisión de deprecar el uso
  público; no prioritaria).
- Generalización de evals de modelo (repo A): un solo LLM, un solo corpus.

## Notas para el próximo agente

- B es el consumidor MCP; NO toca el núcleo de memoria (repo A).
- Los veredictos FALSA de los evals (repo A) son el resultado esperado y
  honesto, no un fallo; el valor medido de la memoria está en C1/C2, la
  rehidratación por re-observación y la discriminación recuerdo/inferencia.
- Convención: pre-registrar en `falsacion.md` antes de medir y documentar
  el resultado (incluso negativo) en el commit.
- La deprecación pública NO toca la operación privada: mantener el server
  funcional es la prioridad del repo B por ahora.

Última actualización: 2026-08-19.