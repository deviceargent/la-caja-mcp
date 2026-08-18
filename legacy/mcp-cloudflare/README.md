# La Caja — Cloudflare MCP

Cloudflare-native implementation of the La Caja deliberation protocol.

## Architecture

- TypeScript Worker
- Streamable HTTP MCP endpoint at `/mcp`
- One private `default-workspace` Durable Object instance
- SQLite-backed Durable Object storage
- Three actor identities: `chatgpt`, `claude`, `human`
- Bearer-token authentication for the MVP

The Python implementation under `mcp/` remains the original protocol reference. This implementation is deliberately not a line-by-line translation: it preserves the demonstrated protocol while moving persistence and execution into Cloudflare's native runtime.

## Current MCP operations

- `get_state`
- `get_entity`
- `search_context`
- `propose`
- `challenge`
- `update_entity`
- `publish_evidence`

## Local development

```bash
npm install
npm run typecheck
npm test
npx wrangler dev
```

The deployed endpoint will be `/mcp`. `/health` is a simple non-MCP health check.

## Secrets

Set these in the Cloudflare Worker before exposing the endpoint:

- `CHATGPT_TOKEN`
- `CLAUDE_TOKEN`
- `HUMAN_TOKEN`

The server infers the actor from the bearer token and does not accept an arbitrary actor supplied by the MCP client.

## Deliberate scope

This first Cloudflare implementation does not yet implement provider-specific OAuth. The bearer-token layer is intentionally small so that authentication can be replaced without changing the deliberation/storage protocol.
