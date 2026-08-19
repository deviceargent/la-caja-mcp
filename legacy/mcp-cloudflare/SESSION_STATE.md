# La Caja Cloudflare MCP — Session State

> **Rol de este archivo (2026-08-19):** además de registrar el estado del
> worker, es el **journal del workspace global** del proyecto La Caja.
> Todo lo que se hace — en cualquier repo — se registra acá, aunque no
> toque el worker de Cloudflare.

## Journal del workspace

Orden cronológico, más reciente primero. Cada entrada referencia el
repo/commit donde vive el cambio.

### 2026-08-19 — independencia La-Caja / la-caja-mcp (decisión de arquitectura)
- **Los dos proyectos siguen siendo independientes.** La-Caja (memoria)
  y `la-caja-mcp` (protocolo) son repos separados, como hoy. El protocolo
  consume la memoria como dependencia (`la-caja` package, `--caja-db`);
  la memoria **nunca** dependerá del protocolo.
- La integración actual es un **escenario de prueba en conjunto** (caso
  de uso real: dos agentes con memoria compartida), NO un desarrollo en
  conjunto. Si el protocolo deja de ser útil, la memoria no se ve
  afectada, y viceversa.

### 2026-08-19 — ciclo de vida del workspace (decisión)
- Este workspace de Cloudflare es, **por ahora, el journal de la
  actividad del proyecto La Caja** (sistema de memoria, MCP, protocolo
  nuevo y lo que surja).
- Cuando se **termine todo lo relacionado con La Caja**, el workspace se
  **extinguirá o se reutilizará para un proyecto independiente nuevo, no
  relacionado** — la decisión se toma en ese momento, no antes.
- Mientras tanto: journaling continuo; el worker sigue en operación
  privada y NO se despliega el protocolo nuevo acá.

### 2026-08-19 — empaquetado, writeup, registro y decisión de deprecación
- **Empaquetado real** en ambos repos (commit A `adb2523`, B `4970672`):
  `pyproject.toml` completo, wheel verificado en venv limpio
  (`la-caja-0.7.0`, `la-caja-mcp-0.1.0`), workflow PyPI `.github/workflows/pypi.yml`
  (trusted publishing; publica al taguear `v*`), README con instalación
  explicada (PyPI / git+ / local).
- **Esqueleto del writeup** (A `experiments/writeup.md`): abstract, método
  y resultados con todos los números medidos; prosa marcada `[PENDIENTE]`.
- **Session state / handoff** creado en A (`SESSION_STATE.md`) y B
  (`SESSION_STATE.md`): registro de todo lo posterior a `e0c5fd6` para el
  próximo agente.
- **Decisión de deprecación:** el MCP de Cloudflare se depreca para uso
  público pero **sigue en operación para uso privado** por ahora, hasta
  la baja definitiva (procedimiento en la sección operativa).
- **Decisión de despliegue:** el nuevo protocolo `la-caja-mcp` NO se mueve
  a Cloudflare; corre como ASGI (uvicorn/Docker). Este worker sigue siendo
  el legacy de deliberación en operación.

### 2026-08-19 — evaluaciones contra modelo (repo A)
- Eval contra modelo (commit A `61c185d`, `experiments/eval_modelo.py`):
  V1/V2/V3 **FALSA** — frecuencia 0.102 > memoria 0.045 > modelo+memoria
  0.027 > modelo_sin_memoria 0.041. gpt-4o-mini vía OpenRouter, 400
  consultas, 0 fallidas.
- Eval de temas dormidos (commit A `81a98c0`, `experiments/eval_dormidos.py`):
  V1-V4 **FALSA** — `techo_hist` 0.030: la traza dormida no predice la
  co-ocurrencia futura; su rol honesto es inercia + rehidratación por
  re-observación.

### 2026-08-19 — validación de rehidratación (repo A)
- Enron (commit A `0a85949`): `hit5_modelo` 0.064→0.070 (+10%), rango
  1-6m 0.0058→0.0082 (**+41%**), techo 0.100→0.126, C2 0.64→0.56.
- Blog (commit A `23b5014`): nula (0.08502→0.08497) — mecanismo
  evento-denso, corpus escaso.

### 2026-08-18 — traza dormida v0.7 (repo A)
- Commit A `fb5edfa`: `historial(termino)`, capa inerte de traza en el
  olvido, rehidratación opt-in (`rehidratar=True`, `MEDIA_VIDA_REHIDRATACION=1500`).
  53 tests.

### 2026-08-18 — cierre de falsación y testing→main (repo A)
- Commit A `75e64da`: resultados canónicos F=3 y conclusión (Enron A/B/C
  ok; Blog A1/B1 refutadas; límite: sin señal ≥ 1 mes).
- Commits A `4797a20`/`7025afb`: la rama `testing` se sube a `main`; el
  MCP de deliberación original se mueve al repo B como `legacy/`.

### 2026-08-18 — creación del nuevo repo la-caja-mcp (repo B)
- **`la-caja-mcp` es la evolución del servidor MCP asíncrono de
  Cloudflare** para la deliberación, llevado al presente:
  - `protocolo.py`: debate agente-agente-humano determinista y replayable
    (evolución de las 7 operaciones del worker TS).
  - Tools de memoria de La Caja (repo A) como consumidor vía API:
    `procesar_consulta`, `declarar_relacion`, `consultar`, `contexto_primado`,
    `historial`, `stats`.
  - Dos transportes: stdio (local) y streamable HTTP (remoto), + push SSE
    (`/caja/push`) para discusión en vivo.
  - `worker/`: host ASGI portable (uvicorn + Dockerfile).
  - **No está desplegado en Cloudflare** y no está en uso para
    comunicarse todavía; su existencia queda registrada aquí.

## Estado operativo (actualizado 2026-08-19)

- **Uso público: se depreca.** No prometer soporte público ni ampliar
  esta implementación para consumo externo.
- **Uso privado: EN OPERACIÓN.** El worker está desplegado y sirviendo
  hoy. NO dar de baja hasta decisión explícita del proyecto.
- **Estado real verificado (2026-08-19, `wrangler` autenticado):**
  - Worker desplegado: `la-caja` (despliegues del 13/8 y 15/8; última
    versión `b400a76e...`, creada 2026-08-15).
  - URL: `https://la-caja.miguel-okstein.workers.dev`
  - `/health` → `200 {"status":"ok"}`.
  - `/mcp` → `401 Unauthorized` sin bearer token (autenticación por
    token, como diseño).
  - Secrets presentes: `CHATGPT_TOKEN`, `CLAUDE_TOKEN`, `HUMAN_TOKEN`,
    `OAUTH_SIGNING_KEY` (y otros). Nunca commitear valores.

## Branch

`cloudflare-mcp` (historial del repo B, movido a `legacy/`).

## Baseline

Esta implementación parte del `mcp-deliberation-mvp` verde. El MCP Python
original sigue siendo la referencia del protocolo.

## Implementación

- TypeScript Cloudflare Worker (`src/index.ts`).
- MCP SDK v2 (`@modelcontextprotocol/server`, `agents/mcp/server`).
- Streamable HTTP remote MCP en `/mcp`.
- Durable Object `CajaState` con storage SQLite.
- Workspace privado único `default-workspace`.
- Siete operaciones de protocolo heredadas del MVP Python.
- Identidad del actor inferida del bearer token (no del argumento).
- Slots de token separados: `chatgpt`, `claude`, `human`.
- `/health` para chequeo básico de despliegue.
- CI smoke tests, typecheck TS y dry-run de Wrangler.

## Autenticación

Bearer-token (no OAuth provider-específico). Los secrets YA están creados
y el worker responde 401 sin token válido.

## Decisión de arquitectura importante

Un solo workspace privado ahora, preservando identidad explícita de actor
y frontera de workspace en el modelo de almacenamiento para un futuro
multi-workspace sin descartar el protocolo.

## Por qué no se basa en McpAgent

`McpAgent` está deprecado/frozen; la doc actual recomienda
`createMcpHandler` con MCP SDK v2 para endpoints MCP stateless. El estado
de la aplicación vive en el Durable Object, no en el estado de sesión MCP.

## Próxima acción

Ninguna inmediata en el worker: está desplegado y operativo para uso
privado. El journal de arriba sigue recibiendo entradas conforme avanza
el proyecto (cada cambio relevante, en cualquier repo). Cuando se decida
la baja definitiva, el orden será: (1) verificar que no haya consumidores
activos, (2) `wrangler delete` del script, (3) borrar los secrets,
(4) registrar la baja en este archivo.