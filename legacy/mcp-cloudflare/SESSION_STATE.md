# La Caja Cloudflare MCP — Session State

## Branch

`cloudflare-mcp`

## Baseline

This branch starts from the green `mcp-deliberation-mvp` implementation. The original Python MCP remains the protocol reference.

## Current implementation

- TypeScript Cloudflare Worker.
- MCP SDK v2 through `@modelcontextprotocol/server` and `agents/mcp/server`.
- Streamable HTTP remote MCP endpoint at `/mcp`.
- SQLite-backed Durable Object `CajaState`.
- One private `default-workspace` instance for the current single-workspace decision.
- Seven protocol operations preserved from the Python MVP.
- Actor identity inferred from bearer token rather than accepting an arbitrary actor argument.
- Separate token slots for `chatgpt`, `claude`, and `human`.
- `/health` endpoint for basic deployment checks.
- CI smoke tests, TypeScript typecheck, and Wrangler dry-run validation.

## Authentication

The current layer is deliberately bearer-token authentication, not provider-specific OAuth. Cloudflare secrets still need to be created before a public deployment is usable:

- `CHATGPT_TOKEN`
- `CLAUDE_TOKEN`
- `HUMAN_TOKEN`

Do not commit token values.

## Important architecture decision

We chose one private workspace now, while preserving explicit actor identity and a workspace boundary in the storage model so a future multi-workspace model does not require discarding the protocol.

## Why this implementation is not based on McpAgent

Current Cloudflare documentation marks `McpAgent` as deprecated/feature-frozen and recommends `createMcpHandler` with MCP SDK v2 for new stateless MCP endpoints. Application state is therefore kept explicitly in the Durable Object rather than in MCP protocol session state.

## Next action

Run GitHub Actions on this branch. Do not deploy until CI is green. If CI passes, return to the Cloudflare dashboard and configure the Worker build/deploy from this branch. Then create the three secrets and deploy. After deployment, test `/health` and the MCP endpoint before connecting Claude or ChatGPT.
