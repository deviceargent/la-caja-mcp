# Worker de ejemplo: host del MCP remoto (streamable HTTP)

El server MCP es Python (FastMCP/ASGI). Un server Python NO corre directo
en Cloudflare Workers (ese entorno es JS/WASM via Pyodide, sin soporte
para apps ASGI con anyio/uvicorn). Por eso el ejemplo de host es un
servidor ASGI portable: sirve EXACTAMENTE el mismo `app` de
`la_caja_mcp.mcp_server` (una tools, dos transportes).

## Correr

```
pip install uvicorn
uvicorn main:app --host 0.0.0.0 --port 8000
# o equivalente:
uvicorn la_caja_mcp.mcp_server:app --host 0.0.0.0 --port 8000
```

Docker:

```
docker build -f worker/Dockerfile -t la-caja-mcp .
docker run -p 8000:8000 la-caja-mcp
```

El endpoint MCP queda en `http://host:8000/mcp`.

## Ponerlo detras de OAuth

MCP remoto exige autorizacion (spec). Opciones:

- Proxy con OAuth (p. ej. oauth2-proxy delante del uvicorn).
- Cualquier gateway que valide tokens antes de dejar pasar al /mcp.
- En un VPS: nginx/caddy con autenticacion en el location /mcp.

## Cloudflare Workers?

Si preferis Workers igual, la mecanica es: un Worker JS/TS como adaptador
que hable MCP streamable HTTP hacia este host (o hacia La Caja) y lo
re-exponga con workers.dev + OAuth. No es reescribir el server: es un
proxy delgado. Este repo no lo incluye porque el host portable cubre el
caso y es el que se puede probar en cualquier lado.

## Probar que el host responde

```
python -m pytest tests -q                      # suite completa
python smoke_http.py                           # ejercita el transporte remoto
```