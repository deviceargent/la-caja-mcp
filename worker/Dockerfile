FROM python:3.12-slim

WORKDIR /srv
COPY . /srv

RUN pip install --no-cache-dir . uvicorn

EXPOSE 8000
CMD ["uvicorn", "la_caja_mcp.mcp_server:app", "--host", "0.0.0.0", "--port", "8000"]