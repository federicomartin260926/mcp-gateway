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
  - `appointment_events`
  - `appointment_confirm`
  - `appointment_reschedule`
  - `appointment_cancel`
  - `appointment_booking_invitation`
  - `services_search`
  - `handoff_request`
  - `crm_contact_submit`
- Incluye la tool real `contact_context`, delegada a un webhook n8n configurable.
- Incluye la tool real `appointment_availability`, delegada a un webhook n8n configurable para disponibilidad de citas.
- Incluye la tool real `services_search`, delegada a un webhook n8n configurable para buscar productos y servicios del CRM.
- Incluye la tool real `handoff_request`, delegada a un webhook n8n configurable para registrar handoffs operativos inferidos por el LLM.
- Incluye la tool real `crm_contact_submit`, delegada a un webhook n8n configurable para enviar contexto comercial al CRM y dejar que CRM decida si crea o actualiza lead, customer o nota.
- Incluye una tool temporal de debug, `debug_auth_context`, habilitable con `MCP_ENABLE_DEBUG_TOOLS=true`, para validar de forma segura si llega `Authorization` desde OpenAI Responses API.
- Añade autenticación Bearer opcional por variable de entorno.
- Permite controlar el `Host` aceptado en `/mcp` por variable de entorno.
- Reenvía `Authorization` recibido por MCP hacia n8n como `X-Downstream-Authorization` para no mezclar la auth técnica del webhook con la auth downstream hacia CRM.
- Usa `Authorization: Bearer <N8N_WEBHOOK_BEARER_TOKEN>` como auth estándar hacia n8n en los webhooks MCP.

## Flujo de trabajo con n8n y Postman

Este proyecto se usa con un flujo práctico para acelerar la creación y validación de tools MCP:

1. Diseñar primero el contrato de la tool MCP.
2. Crear o importar el workflow n8n.
3. Probar el webhook n8n directo con Postman o `curl`.
4. Implementar la tool MCP real en `mcp-gateway`.
5. Probar `/info` y `tools/list`.
6. Probar end-to-end desde `sales-agent` con OpenAI Responses API y MCP remoto.

La guía operativa completa está en [docs/n8n-postman-workflow.md](docs/n8n-postman-workflow.md).

## Estado actual de agenda

- `contact_context` ya validado.
- `appointment_availability` ya validado.
- `appointment_events` ya validado.
- `services_search` ya validado.
- `appointment_confirm`, `appointment_reschedule`, `appointment_cancel` y `appointment_booking_invitation` expuestos como tools MCP.
- `handoff_request` expuesta como tool MCP para handoffs inferidos por LLM.
- `crm_contact_submit` expuesta como tool MCP para enviar contexto comercial a CRM.

## Downstream authorization

Cuando OpenAI Responses API entrega `Authorization` al endpoint MCP, `mcp-gateway` lo reenvía a n8n como `X-Downstream-Authorization`.

n8n toma ese header y lo usa como `Authorization` hacia CRM cuando está presente. Si no llega, los workflows conservan el token CRM por defecto que ya tenían configurado.

Los exports de respaldo del workflow n8n activo se guardan en [docs/n8n-backups/](docs/n8n-backups/).

## CRM contact submit

Variables de entorno:

- `CRM_CONTACT_SUBMIT_WEBHOOK_URL`
- `CRM_CONTACT_SUBMIT_WEBHOOK_TOKEN`
- `CRM_CONTACT_SUBMIT_TIMEOUT_SECONDS`

La tool `crm_contact_submit` envía contexto comercial de una conversación o contacto a un webhook n8n, y n8n solo debe reenviar `crm_payload` al endpoint genérico de CRM.
CRM resuelve el tenant por su token de integración y decide si crea o actualiza lead, customer y/o nota interna.
Si `CRM_CONTACT_SUBMIT_WEBHOOK_URL` no está configurada, la tool devuelve `status: "not_configured"` y no llama al upstream.
Si `CRM_CONTACT_SUBMIT_WEBHOOK_TOKEN` está vacío, la tool usa `N8N_WEBHOOK_BEARER_TOKEN` como token de servicio.
Si ambos tokens están vacíos, el webhook n8n queda sin auth técnica y la tool sigue funcionando solo si ese endpoint la acepta.
Si la request MCP original llevaba `Authorization`, también se reenvía a n8n como `X-Downstream-Authorization`.

### Input

```json
{
  "contact": {
    "name": "Luis Lopez",
    "phone": "+34617214814",
    "email": null,
    "whatsapp_name": "Luis"
  },
  "source": "whatsapp",
  "channel": "whatsapp",
  "external_conversation_id": "whatsapp:+34617214814",
  "entry_point_ref": "wa-mary-main",
  "qualification": {
    "is_qualified": true,
    "service_interest": "Depilación láser axilas",
    "need": "Quiere información y disponibilidad",
    "urgency": "medium",
    "preferred_date": null,
    "preferred_time": "afternoon"
  },
  "conversation": {
    "summary": "El contacto preguntó por depilación láser de axilas y disponibilidad por la tarde.",
    "last_message": "¿Tenéis hueco por la tarde?",
    "intent": "booking_interest",
    "needs_human": false,
    "finished": false
  },
  "actions": {
    "booking_requested": true,
    "handoff_requested": false,
    "waitlist_requested": false
  },
  "metadata": {
    "origin": "sales_agent",
    "sa_conversation_id": "019...",
    "service_slug": "laser-axilas",
    "service_integration_key": null,
    "product_id": null,
    "utm_source": null,
    "utm_medium": null,
    "utm_campaign": null,
    "utm_content": null,
    "utm_term": null
  }
}
```

### Reglas

- `contact` es obligatorio
- exige al menos `contact.phone` o `contact.email`
- normaliza strings vacíos, `"null"` y `"undefined"` a `null`
- convierte el payload enviado a n8n a `crm_payload` en camelCase
- envía `Authorization: Bearer <CRM_CONTACT_SUBMIT_WEBHOOK_TOKEN>` si existe; en caso contrario usa `N8N_WEBHOOK_BEARER_TOKEN`
- si la request MCP original llevaba `Authorization`, también lo reenvía a n8n como `X-Downstream-Authorization`
- usa `CRM_CONTACT_SUBMIT_TIMEOUT_SECONDS` con valor por defecto `8`

### Payload enviado a n8n

```json
{
  "event": "sales_agent.crm_contact_submit",
  "tool": "crm_contact_submit",
  "source": "mcp-gateway",
  "channel": "whatsapp",
  "contact": {
    "name": "Luis Lopez",
    "phone": "+34617214814",
    "email": null,
    "whatsapp_name": "Luis"
  },
  "crm_payload": {
    "source": "whatsapp",
    "channel": "whatsapp",
    "externalConversationId": "whatsapp:+34617214814",
    "entryPointRef": "wa-mary-main",
    "contact": {
      "name": "Luis Lopez",
      "phone": "+34617214814",
      "email": null,
      "whatsappName": "Luis"
    },
    "qualification": {
      "isQualified": true,
      "serviceInterest": "Depilación láser axilas",
      "need": "Quiere información y disponibilidad",
      "urgency": "medium",
      "preferredDate": null,
      "preferredTime": "afternoon"
    },
    "conversation": {
      "summary": "El contacto preguntó por depilación láser de axilas y disponibilidad por la tarde.",
      "lastMessage": "¿Tenéis hueco por la tarde?",
      "intent": "booking_interest",
      "needsHuman": false,
      "finished": false
    },
    "actions": {
      "bookingRequested": true,
      "handoffRequested": false,
      "waitlistRequested": false
    },
    "metadata": {
      "origin": "sales_agent",
      "saConversationId": "019...",
      "serviceSlug": "laser-axilas",
      "serviceIntegrationKey": null,
      "productId": null,
      "utmSource": null,
      "utmMedium": null,
      "utmCampaign": null,
      "utmContent": null,
      "utmTerm": null
    }
  }
}
```

### Output esperado

```json
{
  "ok": true,
  "submitted": true,
  "status": "accepted",
  "message": "CRM contact context submitted.",
  "crm_result": {
    "ok": true,
    "status": "customer_updated",
    "decision": "customer_updated",
    "contactType": "customer",
    "contactId": "crm-contact-1",
    "activityCreated": true,
    "summaryStored": true,
    "warnings": []
  }
}
```

Si hay error de configuración, validación o upstream, la tool devuelve `ok: false`, `submitted: false`, un `status` controlado y un `message` útil. Si n8n devuelve error explícito, se expone también `error` sin tokens ni headers sensibles.

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

## Desarrollo con ngrok y proxy local

Para exponer `mcp-gateway` local a OpenAI Responses API durante desarrollo usamos un dominio ngrok estable.

En este entorno el túnel no apunta directamente a `mcp-gateway`. Primero entra por `dev-router`, un Nginx local que actúa como proxy y reexpone `/mcp`, `/health` e `/info` antes de pasar el tráfico a la app.

Variables requeridas en `.env`:

```bash
NGROK_AUTHTOKEN=...
NGROK_DOMAIN=lavish-supply-custodian.ngrok-free.dev
```

Levantado del túnel:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile tunnel up -d
```

Eso levanta:

- `mcp-gateway`
- `dev-router`
- `mcp-gateway-ngrok`

Estado:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile tunnel ps
```

Logs:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile tunnel logs -f mcp-gateway ngrok
```

URL pública estable:

```text
https://lavish-supply-custodian.ngrok-free.dev/mcp
```

Validación pública:

```bash
curl -i https://lavish-supply-custodian.ngrok-free.dev/health
curl -i -X POST https://lavish-supply-custodian.ngrok-free.dev/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "ngrok-skip-browser-warning: true" \
  -d '{}'
```

Resultado esperado:

- `/health` responde `200 OK`
- `/mcp` con `{}` responde `400` con error de validación JSON-RPC

`dev-router` se encarga de reenviar `Host: localhost:8010` hacia `mcp-gateway`, así que el host que ve la app ya no depende de que `ngrok` apunte directo al backend.

## Host validation MCP

`MCP_ALLOWED_HOSTS` controla qué `Host` acepta el endpoint `/mcp`.

Formato:

- lista separada por comas
- soporta hosts exactos
- para desarrollo con ngrok estable, usa `localhost,127.0.0.1,lavish-supply-custodian.ngrok-free.dev`

Valores recomendados:

- desarrollo local: `localhost,127.0.0.1,lavish-supply-custodian.ngrok-free.dev`
- producción: `mcp.tech-investments.net`

Si `MCP_ALLOWED_HOSTS` está vacío, no se aplica validación adicional por la app.

## Tool debug temporal

Si `MCP_ENABLE_DEBUG_TOOLS=true`, el servidor registra la tool temporal `debug_auth_context`.

- no expone el token completo
- devuelve solo `has_authorization`, `authorization_scheme` y un `token_preview` enmascarado
- sirve para validar si OpenAI Responses API entrega el header `Authorization` durante `tools/list` y `tools/call`

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
- si la request MCP original llevaba `Authorization`, también lo reenvía a n8n como `X-Downstream-Authorization`
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
- si la request MCP original llevaba `Authorization`, también lo reenvía a n8n como `X-Downstream-Authorization`
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

## Appointment actions

Estas tools comparten el mismo patrón de integración con n8n:

- `appointment_confirm`
- `appointment_reschedule`
- `appointment_cancel`
- `appointment_booking_invitation`

Variables de entorno:

- `APPOINTMENT_CONFIRM_WEBHOOK_URL`
- `APPOINTMENT_CONFIRM_TIMEOUT_SECONDS`
- `APPOINTMENT_RESCHEDULE_WEBHOOK_URL`
- `APPOINTMENT_RESCHEDULE_TIMEOUT_SECONDS`
- `APPOINTMENT_CANCEL_WEBHOOK_URL`
- `APPOINTMENT_CANCEL_TIMEOUT_SECONDS`
- `APPOINTMENT_BOOKING_INVITATION_WEBHOOK_URL`
- `APPOINTMENT_BOOKING_INVITATION_TIMEOUT_SECONDS`
- `N8N_WEBHOOK_BEARER_TOKEN`

Cada tool normaliza entradas vacías, aplica defaults razonables y devuelve un payload controlado con `ok`, `message` y `error_code` cuando corresponde.
Si el webhook no está configurado, responde con `error_code: "not_configured"` sin llamar al upstream.

## Services search

Variables de entorno:

- `SERVICES_SEARCH_WEBHOOK_URL`
- `SERVICES_SEARCH_TIMEOUT_SECONDS`
- `N8N_WEBHOOK_BEARER_TOKEN`

La tool `services_search` consulta productos y servicios reales delegando en un webhook n8n.
Si `SERVICES_SEARCH_WEBHOOK_URL` no está configurada, devuelve un payload normalizado con `error_code: "not_configured"` y no llama al upstream.

### Input

```json
{
  "tenant_id": "string | null",
  "query": "string | null",
  "bookable": "boolean | null",
  "active": true,
  "category": "string | null",
  "limit": 10
}
```

### Reglas

- normaliza strings vacíos, `"null"` y `"undefined"` a `null`
- limita `limit` entre `1` y `30`
- envía `Authorization: Bearer <N8N_WEBHOOK_BEARER_TOKEN>` solo si el token existe y no está vacío
- si la request MCP original llevaba `Authorization`, también lo reenvía a n8n como `X-Downstream-Authorization`
- usa `SERVICES_SEARCH_TIMEOUT_SECONDS` con valor por defecto `8`

### Payload enviado a n8n

```json
{
  "tool": "services_search",
  "tenant_id": "019dddb7-db7b-7cdd-963e-4294476ba1e7",
  "query": "whatsapp",
  "bookable": null,
  "active": true,
  "category": null,
  "limit": 10,
  "source": "mcp-gateway"
}
```

### Output esperado

```json
{
  "ok": true,
  "found": true,
  "count": 4,
  "items": [
    {
      "id": "...",
      "name": "...",
      "slug": "...",
      "integration_key": "...",
      "description": "...",
      "base_price_cents": 120000,
      "currency": "EUR",
      "category": {
        "id": "...",
        "name": "Automatización",
        "slug": "automation"
      },
      "is_bookable": false,
      "is_billable": true,
      "duration_minutes": null,
      "buffer_before_minutes": 0,
      "buffer_after_minutes": 0,
      "active": true
    }
  ],
  "categories": [],
  "message": "...",
  "raw_summary": {}
}
```

Si hay error de configuración, validación o upstream, la tool devuelve `ok: false`, `found: false`, `count: 0`, `items: []`, `categories: []`, `message` útil y `error_code`.

## Handoff request

Variables de entorno:

- `HANDOFF_REQUEST_WEBHOOK_URL`
- `HANDOFF_REQUEST_WEBHOOK_TOKEN`
- `HANDOFF_REQUEST_TIMEOUT_SECONDS`

La tool `handoff_request` registra un handoff operativo inferido por el LLM delegando en un webhook n8n.
Si `HANDOFF_REQUEST_WEBHOOK_URL` no está configurada, devuelve un payload normalizado con `status: "not_configured"` y no llama al upstream.
Si `HANDOFF_REQUEST_WEBHOOK_TOKEN` está vacío, la tool usa `N8N_WEBHOOK_BEARER_TOKEN` como token de servicio.
Si ambos tokens están vacíos, la tool devuelve `status: "not_configured"` y no llama al upstream.
En local, si el workflow n8n está publicado, usa `http://host.docker.internal:5680/webhook/sa-handoff-request`.
Si estás escuchando manualmente el workflow en modo test, cambia a `http://host.docker.internal:5680/webhook-test/sa-handoff-request`.

Payload recomendado:

- `tenant_id`
- `reason`
- `priority` cuando pueda inferirse
- `message` con el último mensaje relevante del usuario
- `contact.name`, `contact.phone`, `contact.email`
- `conversation.id`, `conversation.external_conversation_id`, `conversation.channel`
- `conversation.summary`
- `conversation.last_messages` acotado a 6-8 mensajes recientes

Ese contexto permite que n8n prepare un email o una tarea humana con suficiente información y deja el mismo contrato listo para un futuro alta de actividad en CRM.

### Input

```json
{
  "tenant_id": "string | null",
  "contact": {
    "phone": "string | null",
    "email": "string | null",
    "name": "string | null",
    "external_id": "string | null"
  },
  "conversation": {
    "id": "string | null",
    "external_conversation_id": "string | null",
    "channel": "string | null",
    "status": "string | null",
    "summary": "string | null",
    "last_messages": ["string"]
  },
  "reason": "string | null",
  "priority": "low | normal | high | urgent",
  "message": "string | null",
  "metadata": {}
}
```

### Reglas

- normaliza strings vacíos, `"null"` y `"undefined"` a `null`
- limita `conversation.last_messages` a los 8 mensajes más recientes
- `priority` acepta `low`, `normal`, `high` y `urgent`; cualquier otro valor se normaliza a `normal`
- envía `Authorization: Bearer <HANDOFF_REQUEST_WEBHOOK_TOKEN>` si el override existe y no está vacío; en caso contrario usa `N8N_WEBHOOK_BEARER_TOKEN`
- si no hay ninguno de los dos tokens, devuelve `status: "not_configured"` y no llama al webhook
- si la request MCP original llevaba `Authorization`, también lo reenvía a n8n como `X-Downstream-Authorization`
- usa `HANDOFF_REQUEST_TIMEOUT_SECONDS` con valor por defecto `8`

### Payload enviado a n8n

```json
{
  "event": "sales_agent.handoff_requested",
  "tenant_id": "019dddb7-db7b-7cdd-963e-4294476ba1e7",
  "contact": {
    "phone": "+34611949358",
    "email": null,
    "name": "Lucia Garcia",
    "external_id": null
  },
  "conversation": {
    "id": "conversation-1",
    "external_conversation_id": "external-conv-1",
    "channel": "whatsapp",
    "status": "pending_human",
    "summary": "Caso sensible.",
    "last_messages": [
      "Mensaje 1",
      "Mensaje 2"
    ]
  },
  "reason": "frustration",
  "priority": "high",
  "message": "El caso necesita revisión humana.",
  "metadata": {
    "source": "mcp-gateway",
    "tool": "handoff_request"
  }
}
```

### Output esperado

```json
{
  "ok": true,
  "handoff_requested": true,
  "status": "accepted",
  "message": "Handoff registrado.",
  "external_reference": null
}
```

Si hay error de configuración, validación o upstream, la tool devuelve `ok: false`, `handoff_requested: false`, un `status` controlado y un `message` útil.

## Tools disponibles

- `echo`
- `contact_context_mock`
- `contact_context`
- `appointment_availability`
- `services_search`
- `handoff_request`
- `crm_contact_submit`

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
- `server_url`: `https://lavish-supply-custodian.ngrok-free.dev/mcp`
- `allowed_tools`: `["echo", "contact_context_mock", "contact_context", "appointment_availability", "services_search", "handoff_request", "crm_contact_submit"]`

Si tu cliente MCP necesita la ruta explícita, usa el endpoint `/mcp`.

### Nota para sales-agent

La `ExternalTool` runtime default del tenant debe apuntar a:

```text
https://lavish-supply-custodian.ngrok-free.dev/mcp
```

En `sales-agent` eso queda persistido en `external_tools.webhook_url` para:

- `type = mcp_remote`
- `provider = openai_remote_mcp`
- `is_runtime_default = true`

No se ejecuta SQL desde este repo; la configuración se gestiona en `sales-agent`/UI.

Para pruebas reales con OpenAI Responses API, el flujo recomendado es validar primero el webhook n8n, después el descubrimiento MCP en `mcp-gateway` y, por último, el uso desde `sales-agent`.

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
  -H 'Authorization: Bearer n8n-bearer-token' \
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

Ejemplo directo para `services_search`:

```bash
curl -sS http://localhost:5680/webhook-test/sa-services-search \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer n8n-bearer-token' \
  -d '{
    "tool": "services_search",
    "tenant_id": "019dddb7-db7b-7cdd-963e-4294476ba1e7",
    "query": "whatsapp",
    "bookable": null,
    "active": true,
    "category": null,
    "limit": 10,
    "source": "mcp-gateway"
  }'
```

Ejemplo esperado desde MCP:

```json
{
  "name": "services_search",
  "arguments": {
    "tenant_id": "019dddb7-db7b-7cdd-963e-4294476ba1e7",
    "query": "whatsapp",
    "active": true,
    "limit": 10
  }
}
```

## Tests

```bash
make test
```
