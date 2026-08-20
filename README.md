# la-caja-mcp

MCP system for access and debate over **La Caja** (contextual memory).
Repo B: consumer of La Caja (repo A). This repo does not touch the memory
core; it talks to it by API and exposes La Caja to agents.

Español: [README.es.md](README.es.md)

## What's here

- `src/la_caja_mcp/protocolo.py` — agent–agent–human debate protocol.
  Claims, interference requests, deadline rounds in turns, escalation and
  human adjudication. Deterministic and replayable (event-sourcing, same
  discipline as La Caja). The state machine is a contract: in `disputed`
  the author can only respond or escalate; `unresolved` (deadlock) is the
  ONLY terminal the human can adjudicate.
- `src/la_caja_mcp/mcp_server.py` — MCP server: debate tools + La Caja
  memory tools (repo A, consumed by API), one tool set and two transports
  (local stdio / remote streamable HTTP).
- `src/la_caja_mcp/install.py` — one-command installer: detects the
  installed MCP agents and writes the correct config entry for each
  (opencode, Claude Code, Cursor, VS Code, Claude Desktop).
- `tests/` — falsification of the state machine + integration with a real
  MCP client over stdio (debate and memory) + multi-agent SSE push (46
  tests).
- `experiments/uso_real.py` — real use case: two LLM agents as MCP
  clients (shared memory, debate, replay, push).
- `experiments/interrupcion_etapas.py` — the protocol's basis: an agent
  mid-reasoning accepts being interrupted and yields within the round.
- `worker/` — portable ASGI host (uvicorn + Dockerfile) for the remote
  MCP.

## Validated with real LLMs (OpenRouter, gpt-4o-mini, over streamable HTTP)

| Validation | Result |
|---|---|
| Real use case (2 MCP agents, shared memory) | **OK** — consensus, replay, push |
| Full interference request (deadline → escalate → human) | **OK** |
| **Interruption mid-reasoning** | **OK** — `proponer → manifestar → interferir → responder → aceptar` |

The protocol basis works: the author exposes its reasoning in stages with
`manifestar` (the interruption medium), checks the state between stages,
the interferer requests `interferir` mid-way, and the interrupted yields
by responding within the round (`vence_en_turnos` intact). Design detail
and limits in the La Caja writeup (`experiments/writeup.md`, repo A).

## Installation

Standard Python package (`la-caja-mcp`), like its dependency `la-caja`
(repo A):

```
# Direct from the repository (works today)
pip install git+https://github.com/deviceargent/la-caja-mcp.git

# Published (PyPI)
pip install la-caja-mcp

# Local development
pip install .
```

Installs the `la-caja-mcp` executable and the dependencies (`fastmcp`,
`la-caja`). The remote worker needs the hosting extra:

```
pip install "la-caja-mcp[host]"    # or  pip install .[host]  in the repo
```

## One-command install (agents)

For the average user who wants "better memory" without hand-editing JSON:

```
la-caja-mcp install                # detects agents and registers everywhere
la-caja-mcp install --agent opencode
la-caja-mcp install --scope global # user-wide config instead of project
la-caja-mcp install --name caja    # entry name (default: caja)
la-caja-mcp install --caja-db <path>   # persistent memory for the server
la-caja-mcp install --list         # only list detected agents
```

It detects the installed agents and writes the config entry each one
reads: opencode (`opencode.json`), Claude Code (`.mcp.json` /
`~/.claude.json`), Cursor (`.cursor/mcp.json`), VS Code (`.vscode/mcp.json`),
Claude Desktop (`claude_desktop_config.json`, including the MSIX/UWP case,
where the app redirects `%APPDATA%` into the package). The server command
is resolved portably with the running Python (`python -m
la_caja_mcp.mcp_server --transport stdio`). Restart your agent to pick the
config up.

## MCP server

One tool set, two transports:

```
# local (stdio): launched by the agent as a subprocess
la-caja-mcp --transport stdio

# remote (streamable HTTP): the standard for MCP over the network
la-caja-mcp --transport streamable-http --host 127.0.0.1 --port 8000
```

Debate: `crear_sesion`, `mover` (JSON payload), `estado`,
`ultimos_eventos`, `reproducir_sesion`.
Memory (needs `pip install la-caja`; repo A): `procesar_consulta`,
`declarar_relacion`, `consultar`, `contexto_primado`, `historial`
(dormant trace, inert layer), `stats`.

Memory is persistent with `--caja-db <path>` (SQLite, La Caja
event-sourcing) or `LA_CAJA_DB`; without it, pure in-memory.

## Live discussion (push)

Over streamable HTTP the server also exposes an SSE endpoint:

```
GET /caja/push?sesion_id=<id>
```

Emits an `estado` event (snapshot: `ultimo_seq` + `estado`) on connect
and then a `sesion_actualizada` per successful `mover()`. An agent
subscribes with a separate HTTP connection (any stack) and uses
`ultimos_eventos` to fetch the detail. Needs a shared server: over stdio
each agent has its own process, there liveliness comes from polling with
`ultimos_eventos`.

## MCP transports (architecture decision)

- Local = `stdio` (the agent launches the server as a subprocess).
- Remote = **streamable HTTP** (the standard for remote MCP, + OAuth).
- `worker/` is an example of a deployable host (VPS/Docker); there is no
  public hosted MCP.

## Test

```
$env:PYTHONPATH="src"; python -m pytest tests -q
python experiments/uso_real.py                    # needs OPENAI_API_KEY
python experiments/interrupcion_etapas.py         # needs OPENAI_API_KEY
```

## License

MIT — see [LICENSE](LICENSE).