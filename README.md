# mcp-gateway

Servidor MCP remoto base para validar herramientas nativas con OpenAI Responses API.

## Qué hace

- Expone un servicio FastAPI dockerizado.
- Sirve un endpoint MCP real compatible con OpenAI Responses API remote MCP en `/mcp`.
- Soporta `initialize`, `tools/list` y `tools/call` vía Streamable HTTP.
- Incluye dos tools iniciales:
  - `echo`
  - `contact_context_mock`
- Añade autenticación Bearer opcional por variable de entorno.
- Permite controlar el `Host` aceptado en `/mcp` por variable de entorno.

## Endpoints

- `GET /health`
- `GET /info`
- `MCP /mcp`

La ruta MCP se expone sin redirect. OpenAI debe poder consultar tools directamente contra `/mcp`.

## Entorno

- Contenedor: `mcp-gateway`
- Puerto interno: `8010`
- Red externa para proxy: `proxy`
- Red interna: `mcp_internal`

## Levantar local

```bash
cp .env.example .env
make up
```

Con el override local, el servicio también queda publicado en `http://localhost:8010`.

## Host validation MCP

`MCP_ALLOWED_HOSTS` controla qué `Host` acepta el endpoint `/mcp`.

Formato:

- lista separada por comas
- soporta hosts exactos
- soporta wildcard de subdominio con `*.trycloudflare.com`

Valores recomendados:

- desarrollo local: `localhost,127.0.0.1,*.trycloudflare.com`
- producción: `mcp.tech-investments.net`

Si `MCP_ALLOWED_HOSTS` está vacío, no se aplica validación adicional por la app.

## Uso con Nginx Proxy Manager

- Host público: `https://mcp.tech-investments.net`
- Forward hostname/IP: `mcp-gateway`
- Forward port: `8010`
- Scheme: `http`

La ruta MCP está disponible en `/mcp`.

## Auth Bearer opcional

Si `MCP_AUTH_TOKEN` tiene valor:

- se exige `Authorization: Bearer <token>`
- si no coincide, responde `401`

Si está vacío:

- el acceso queda abierto para desarrollo

## Tools disponibles

- `echo`
- `contact_context_mock`

### `echo`

Input:

```json
{ "message": "string" }
```

Output:

```json
{ "message": "string", "echoed": true }
```

### `contact_context_mock`

Input:

```json
{ "phone": "string | null", "email": "string | null" }
```

Output:

```json
{
  "found": true,
  "contact": {
    "name": "Cliente Demo",
    "status": "lead",
    "stage": "new",
    "last_interaction": "mock"
  }
}
```

## Integración con sales-agent

Configura la `ExternalTool` MCP remota en `sales-agent` con algo como:

- `type`: `mcp_remote`
- `provider`: `openai_remote_mcp`
- `server_label`: `tech_investments_mcp`
- `server_url`: `https://mcp.tech-investments.net`
- `allowed_tools`: `["echo", "contact_context_mock"]`

Si tu cliente MCP necesita la ruta explícita, usa el endpoint `/mcp`.

## Validación local

Para validar descubrimiento MCP real sin tocar `sales-agent`:

```bash
make mcp-smoke
```

Ese test ejecuta `initialize`, `tools/list` y `tools/call` contra `/mcp`.

## Tests

```bash
make test
```
