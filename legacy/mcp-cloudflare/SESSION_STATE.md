# La Caja Cloudflare MCP — Session State

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

Ninguna inmediata: está desplegado y operativo para uso privado. Cuando
se decida la baja definitiva, el orden será: (1) verificar que no haya
consumidores activos, (2) `wrangler delete` del script, (3) borrar los
secrets, (4) registrar la baja en este archivo.