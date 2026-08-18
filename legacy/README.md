# legacy/ — MCP de deliberación original (retirado)

Los artefactos del MCP de deliberación que vivían en el `main` de
`La-Caja` antes de la separación de repos (A = memoria, B = acceso MCP).
Se conservan aquí como **referencia de la mecánica** y porque el worker
de Cloudflare que hay desplegado aún puede retirarse con esta base.

## Contenido

- `mcp/` — server Python **asíncrono** de deliberación (SQLite +
  Markdown): `get_state`, `get_entity`, `search_context`, `propose`,
  `challenge`, `update_entity`, `publish_evidence`. El protocolo de
  estado (candidate/disputed/conditional/consensus/...) que lo inspira
  ahora está implementado de forma determinista y replayable en
  `src/la_caja_mcp/protocolo.py` (raíz de este repo).
- `mcp-cloudflare/` — worker de Cloudflare (index.ts, wrangler) que
  sirvió el endpoint público `la-caja-mcp.miguel-okstein.workers.dev/mcp`
  con OAuth de un solo tenant. **Se va a retirar**: el host actual del
  MCP remoto es `worker/` (raíz de este repo, ASGI portable).
- `wrangler.jsonc`, `package.json` — config de despliegue raíz del
  worker.
- `.github/workflows/` — CI del proyecto original (referencia).

## Tokens

No hay valores de tokens commiteados. El worker usa secrets de
Cloudflare (`CHATGPT_TOKEN`, `CLAUDE_TOKEN`, `HUMAN_TOKEN` vía `env.*`).
Al retirar el worker: eliminar los secrets y el deployment.

## Actor

El worker infiere el actor del bearer token (nunca del argumento del
cliente). Nota histórica: el token humano se registró como `chatgpt` en
la primera pasada del MVP (bug de actores que quedó corregido en la
inferencia por token, SESSION_STATE.md).