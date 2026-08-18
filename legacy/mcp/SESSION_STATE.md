# La Caja MCP — Session State

## Current branch

`mcp-deliberation-mvp`

## What has been implemented

- Minimal MCP server under `mcp/`.
- SQLite-backed entities and immutable deliberation events.
- Seven initial operations: `get_state`, `get_entity`, `search_context`, `propose`, `challenge`, `update_entity`, `publish_evidence`.
- Entity existence checks and SQLite foreign-key enforcement.
- `get_state` returns the complete event history rather than silently truncating at 50 events.
- `search_context` searches entity metadata and event content.
- Status transitions preserve their history.
- Initial protocol tests under `mcp/tests/test_protocol.py`.
- GitHub Actions workflow added at `.github/workflows/mcp-tests.yml` to install the package and run the protocol tests on pushes to this branch and on pull requests.

## CI status

**GREEN — 6/6 protocol tests pass in GitHub Actions.**

The first CI run failed before any protocol test could execute:

`ModuleNotFoundError: No module named 'mcp.server.fastmcp'`

Root cause: the dependency was declared as `mcp>=1.0.0`, which allowed the current MCP SDK v2 while the server uses the v1 `FastMCP` import path. The dependency was constrained to `mcp>=1.28,<2` for this MVP rather than silently migrating the server to v2.

A subsequent CI run passed all six protocol tests. This is the first verified green baseline for the MVP.

## Deliberately NOT implemented yet

- Provider-specific OAuth / authentication for ChatGPT and Claude.
- Public HTTPS deployment / remote MCP transport.
- Final epistemic model (consensus, conditional agreement, candidates, incompatibility).
- Automatic consensus logic.
- Full La Caja architecture.
- Vector search or semantic retrieval.
- Production persistence/deployment concerns beyond the local SQLite MVP.

These are intentionally deferred. Do not silently treat them as solved.

## Current adversarial test targets

1. Proposal can be created and retrieved.
2. Unknown-entity challenge must not create an orphan event.
3. Status transitions preserve proposal/challenge/status history.
4. Invalid statuses are rejected.
5. Search must find event content.
6. State retrieval must not silently drop older events.

## Notes for the next agent/session

This project is being developed as an adversarial/collaborative research workspace between independent LLM agents. The server should preserve disagreement and provenance rather than deciding truth. Agents may bring external evidence and proposals between sessions. The architecture is expected to emerge incrementally from actual use.

Last update: CI is green; 6/6 protocol tests pass. Next step is to inspect/review the green baseline and then proceed toward the deferred authentication/remote-MCP work without pretending those pieces already exist.
