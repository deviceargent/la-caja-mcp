"""Host ASGI del server MCP (transporte streamable HTTP).

Ejemplo de despliegue portable: un server Python no corre directo en
Cloudflare Workers (entorno JS/WASM), asi que este host sirve el mismo
app de la_caja_mcp.mcp_server con uvicorn, listo para VPS, Docker o
cualquier runtime con ASGI.

Uso:
    uvicorn main:app --host 0.0.0.0 --port 8000
"""

from la_caja_mcp.mcp_server import app

__all__ = ["app"]