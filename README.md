# mcp-gateway

Servidor MCP remoto base para validar herramientas nativas con OpenAI Responses API.

## Qué hace

- Expone un servicio FastAPI dockerizado.
- Sirve un endpoint MCP real compatible con OpenAI Responses API remote MCP en `/mcp`.
- Soporta `initialize`, `tools/list` y `tools/call` vía Streamable HTTP.
- Incluye tools iniciales:
  - `echo`
  - `contact_context_mock`
  - `contact_context`
  - `appointment_availability`
- Incluye la tool real `contact_context`, delegada a un webhook n8n configurable.
- Incluye la tool real `appointment_availability`, delegada a un webhook n8n configurable para disponibilidad de citas.
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

## Desarrollo con Cloudflare Tunnel

Para levantar el stack de desarrollo con el túnel desde Docker Compose:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
```

Para ver la URL pública que asigna `cloudflared`:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml logs -f cloudflared
```

También puedes verla en Docker Desktop, dentro del contenedor `cloudflared`, en la pestaña `Logs`.
La URL `https://<algo>.trycloudflare.com` que aparezca ahí es la que debes copiar en la URL del servidor MCP correspondiente, por ejemplo en `sales-agent`.

Validación local:

```bash
curl -sS http://localhost:8010/health | jq
curl -sS http://localhost:8010/info | jq
```

Validación pública:

```bash
curl -sS https://<url-trycloudflare>/health | jq
curl -sS https://<url-trycloudflare>/info | jq
```

La URL a configurar en `sales-agent` es:

```text
https://<url-trycloudflare>/mcp
```

La URL del quick tunnel es temporal y puede cambiar al recrear el contenedor `cloudflared`.
Para un entorno estable a futuro, conviene migrar a un named tunnel con dominio fijo.

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

## Contact context

Variables de entorno:

- `CONTACT_CONTEXT_WEBHOOK_URL`
- `N8N_WEBHOOK_BEARER_TOKEN`
- `CONTACT_CONTEXT_TIMEOUT_SECONDS`

La tool `contact_context` consulta contexto comercial real delegando en un webhook n8n.
Si `CONTACT_CONTEXT_WEBHOOK_URL` no está configurada, la tool devuelve un payload normalizado con `error_code: "not_configured"` y no llama al upstream.

### Input

```json
{
  "phone": "string | null",
  "email": "string | null",
  "name": "string | null",
  "tenant_id": "string | null",
  "channel": "string | null"
}
```

### Reglas

- exige al menos `phone` o `email` cuando hay webhook configurado
- normaliza strings vacíos, espacios y valores tipo `"null"` a `null`
- envía `Authorization: Bearer <N8N_WEBHOOK_BEARER_TOKEN>` solo si el token existe y no está vacío
- usa `CONTACT_CONTEXT_TIMEOUT_SECONDS` con valor por defecto `5`

### Payload enviado a n8n

```json
{
  "tool": "contact_context",
  "tenant_id": "string | null",
  "contact": {
    "phone": "string | null",
    "email": "string | null",
    "name": "string | null"
  },
  "channel": "string | null",
  "source": "mcp-gateway"
}
```

### Output normalizado esperado

```json
{
  "found": true,
  "contact": {
    "name": "Cliente Demo",
    "type": "lead",
    "status": "lead",
    "stage": "new",
    "owner": null,
    "last_interaction": null
  },
  "appointments": {
    "next": null,
    "items": []
  },
  "open_opportunities": [],
  "sales": {},
  "flags": {
    "needs_human": false,
    "do_not_contact": false
  },
  "summary": "Resumen breve útil para el LLM"
}
```

Si hay error de configuración, validación o upstream, la tool devuelve el mismo esquema con `found: false`, `summary` útil para el LLM y `error_code`.

## Appointment availability

Variables de entorno:

- `APPOINTMENT_AVAILABILITY_WEBHOOK_URL`
- `APPOINTMENT_AVAILABILITY_TIMEOUT_SECONDS`
- `N8N_WEBHOOK_BEARER_TOKEN`

La tool `appointment_availability` consulta huecos de agenda reales delegando en un webhook n8n.
Si `APPOINTMENT_AVAILABILITY_WEBHOOK_URL` no está configurada, devuelve un payload normalizado con `error_code: "not_configured"` y no llama al upstream.

### Input

```json
{
  "tenant_id": "string | null",
  "date_from": "string",
  "date_to": "string",
  "timezone": "string | null",
  "duration_minutes": 30,
  "limit": 6,
  "service_ref": "string | null",
  "owner_ref": "string | null",
  "contact": {
    "phone": "string | null",
    "email": "string | null",
    "name": "string | null"
  }
}
```

### Reglas

- exige `date_from` y `date_to`
- normaliza strings vacíos, espacios y valores tipo `"null"` a `null`
- `timezone` usa `Europe/Madrid` por defecto
- `duration_minutes` se limita entre `5` y `240`
- `limit` se limita entre `1` y `10`
- envía `Authorization: Bearer <N8N_WEBHOOK_BEARER_TOKEN>` solo si el token existe y no está vacío
- usa `APPOINTMENT_AVAILABILITY_TIMEOUT_SECONDS` con valor por defecto `8`

### Payload enviado a n8n

```json
{
  "tool": "appointment_availability",
  "tenant_id": "string | null",
  "date_from": "2026-05-11",
  "date_to": "2026-05-15",
  "timezone": "Europe/Madrid",
  "duration_minutes": 30,
  "limit": 6,
  "service_ref": "string | null",
  "owner_ref": "string | null",
  "contact": {
    "phone": "string | null",
    "email": "string | null",
    "name": "string | null"
  },
  "source": "mcp-gateway"
}
```

### Output esperado

```json
{
  "ok": true,
  "available": true,
  "timezone": "Europe/Madrid",
  "slots": [
    {
      "start": "2026-05-11T09:00:00+02:00",
      "end": "2026-05-11T09:30:00+02:00",
      "label": null,
      "owner": {
        "id": "019c33aa-5f3d-729d-933e-3a8c28a2e66d",
        "name": "Carla",
        "email": "agente@gmail.com",
        "preferred": false
      }
    }
  ],
  "message": "Hay 6 hueco(s) disponible(s) de 6 encontrados.",
  "raw_summary": {
    "mode": "multi_owner",
    "durationMinutes": 30,
    "ownersCount": 3,
    "totalSlots": 6,
    "returnedSlots": 6,
    "preferredOwnerId": null,
    "preferredOwnerName": null
  }
}
```

Si hay error de configuración, validación o upstream, la tool devuelve `ok: false`, `available: false`, `slots: []`, `message` útil y `error_code`.

## Tools disponibles

- `echo`
- `contact_context_mock`
- `contact_context`
- `appointment_availability`

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
- `allowed_tools`: `["echo", "contact_context_mock", "contact_context", "appointment_availability"]`

Si tu cliente MCP necesita la ruta explícita, usa el endpoint `/mcp`.

## Validación local

Para validar descubrimiento MCP real sin tocar `sales-agent`:

```bash
make mcp-smoke
```

Ese test ejecuta `initialize`, `tools/list` y `tools/call` contra `/mcp`.

Smoke test rápido:

```bash
curl -s http://localhost:8010/info | jq '.available_tools'
```

o contra MCP:

```bash
curl -s http://localhost:8010/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

Smoke test directo contra n8n:

```bash
curl -sS http://localhost:5680/webhook-test/sa-appointment-availability \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer n8n_integrations_service_token_local' \
  -d '{
    "tool": "appointment_availability",
    "tenant_id": "019dddb7-db7b-7cdd-963e-4294476ba1e7",
    "date_from": "2026-05-11",
    "date_to": "2026-05-15",
    "timezone": "Europe/Madrid",
    "duration_minutes": 30,
    "limit": 6,
    "service_ref": null,
    "owner_ref": null,
    "contact": {
      "phone": "+34611949358",
      "email": null,
      "name": "Lucia Garcia"
    },
    "source": "mcp-gateway"
  }'
```

## Tests

```bash
make test
```
