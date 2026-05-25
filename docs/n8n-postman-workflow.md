# Flujo n8n + Postman para tools MCP

Esta guía documenta el flujo de trabajo recomendado para crear, modificar y validar workflows n8n que sirven como backend de tools MCP en `mcp-gateway`.

La idea es mantener el desarrollo rápido y predecible:

1. Definir el contrato de la tool MCP.
2. Construir o importar el workflow n8n.
3. Probar el webhook n8n directo con Postman o `curl`.
4. Implementar la tool MCP real en `mcp-gateway`.
5. Validar `GET /info` y `tools/list`.
6. Probar end-to-end desde `sales-agent` con OpenAI Responses API y MCP remoto.

## Flujo recomendado

### 1. Diseñar primero el contrato

Antes de tocar n8n, define:

- nombre de la tool MCP
- input mínimo necesario
- salida esperada para LLM
- campos obligatorios para escritura
- código de error normalizado

Esto evita workflows demasiado grandes y respuestas difíciles de usar desde el LLM.

### 2. Crear o importar el workflow n8n

Usa n8n como capa de integración y deja que el workflow resuelva:

- recepción del webhook
- preparación del payload
- llamada a CRM o API externa
- normalización de salida
- respuesta final al webhook

### 3. Probar el webhook n8n directo

Antes de conectar `mcp-gateway`, prueba el webhook con:

- Postman
- `curl`
- `Listen for test event` en n8n

La validación directa debe confirmar que el workflow responde bien sin depender de MCP.

### 4. Implementar la tool MCP en `mcp-gateway`

Una vez validado el webhook, se implementa o ajusta la tool MCP real para que delegue en n8n.

### 5. Probar descubrimiento MCP

Valida:

- `GET /info`
- `tools/list`

Si eso funciona, el contrato MCP ya está visible para clientes remotos.

### 6. Probar end-to-end desde `sales-agent`

La última validación es desde `sales-agent` con OpenAI Responses API y MCP remoto.

## Exportar desde n8n

### Exportar workflow completo

Cuando quieras reutilizar una automatización completa:

- exporta el workflow entero como JSON
- úsalo como base para generar una variante nueva
- pásalo a ChatGPT como contexto para crear workflows similares

### Exportar nodos o subflujos

Cuando no haga falta el workflow completo:

- copia nodos concretos
- exporta solo el subflujo relevante
- reutiliza esa estructura para `events`, `cancel` o `reschedule`

### Reasignar credenciales tras importar

n8n no siempre conserva credenciales de forma útil al importar JSON.

Después de importar, revisa y reasigna:

- credenciales de `Webhook Header Auth`
- credenciales hacia CRM o API externa
- credenciales de nodos auxiliares si existen

## Importar en n8n

### Pasos básicos

1. Importa el JSON generado.
2. Revisa el nodo `Webhook`.
3. Revisa las credenciales.
4. Revisa los headers hacia CRM/API externa.
5. Ejecuta pruebas con `Listen for test event`.
6. Activa producción solo cuando el flujo esté validado.

### Credenciales y URLs a revisar

- Webhook Header Auth: normalmente `Lead T&I Webhook Bearer`
- n8n local: `http://localhost:5680`
- CRM desde n8n Docker/local: `http://host.docker.internal:8082`
- `mcp-gateway` local: `http://localhost:8010`

### Verificación antes de activar

Antes de pasar a producción en n8n:

- confirma que el webhook responde con el JSON esperado
- confirma que los headers de autenticación son correctos
- confirma que las URLs no apuntan a entornos equivocados

## Naming recomendado

### Workflows

- `SA Contact Context`
- `SA Appointment Availability`
- `SA Appointment Confirm`
- `SA Appointment Events`
- `SA Appointment Cancel`
- `SA Appointment Reschedule`

### Webhook paths

- `sa-contact-context`
- `sa-appointment-availability`
- `sa-appointment-confirm`
- `sa-appointment-events`
- `sa-appointment-cancel`
- `sa-appointment-reschedule`

## Estructura recomendada de cada workflow

Usa esta secuencia como base:

1. `Webhook`
2. `Prepare payload/query`
3. `HTTP Request` a CRM o API externa
4. `Normalize output`
5. `Respond to Webhook`

### Tools de lectura

Para lecturas como contextos o disponibilidad:

- devolver salida pequeña
- normalizar campos
- dejar solo datos accionables para el LLM
- limitar arrays
- evitar payloads raw gigantes

### Tools de escritura

Para confirmaciones, cancelaciones y reprogramaciones:

- validar inputs obligatorios
- devolver `confirmed`, `sent`, `updated` o `cancelled` según corresponda
- nunca devolver stacktraces al LLM
- incluir `error_code` normalizado cuando falle algo

## Uso de Postman

Mantén una colección del proyecto para probar webhooks n8n.

### Variables recomendadas

- `n8n_base_url=http://localhost:5680`
- `n8n_webhook_bearer_token=n8n-bearer-token`
- `tenant_id`
- `existing_customer_phone`
- `existing_customer_name`
- `customer_id`
- `appointment_id`
- `owner_id`

### Estructura de la colección

- un request por tool
- un request por webhook n8n
- ejemplos claros para lectura y escritura

### Tests mínimos

Cada request debería validar al menos:

- `status 200`
- `ok true` o `error_code` controlado
- estructura de output esperada

### Orden de prueba

1. Probar primero n8n directo.
2. Después validar `mcp-gateway`.
3. Por último probar desde `sales-agent`.

## Advertencias

- Los webhooks test de n8n requieren `Listen for test event`.
- Las URLs de quick tunnel de Cloudflare quedaron descartadas para este flujo.
- El flujo recomendado de desarrollo remoto usa ngrok con dominio estable.
- Las credenciales de n8n pueden requerir reasignación tras importar.
- `confirm`, `cancel` y `reschedule` modifican datos reales en CRM.
- No guardar tokens reales en JSON exportados ni en git.
- Mantener tokens locales de ejemplo solo para dev.
- Para validar `mcp-gateway` remoto desde OpenAI Responses API, usar `https://lavish-supply-custodian.ngrok-free.dev/mcp`.

## Estado actual de agenda

El flujo de agenda va así:

- `contact_context` ya validado.
- `appointment_availability` ya validado.
- `appointment_confirm` ya validado en n8n.
- `appointment_events`, `appointment_cancel` y `appointment_reschedule` preparados como workflows importables.
- La colección Postman asociada está actualizada para seguir validando los webhooks antes de exponer la tool MCP final.

## Prompt template para ChatGPT

Plantillas cortas que funcionan bien para acelerar iteraciones:

```text
Te paso el JSON exportado de n8n. Genera un workflow importable con la misma estructura para la tool X, manteniendo la lógica principal, pero devolviendo una salida pequeña, normalizada y accionable para LLM.
```

```text
Actualiza esta colección Postman agregando requests para estos webhooks n8n, con variables de entorno, tests mínimos y ejemplos de payload para lectura y escritura.
```

```text
Basándote en este workflow existente, crea subflujos separados para events, cancel y reschedule, respetando el naming recomendado y la estructura Webhook -> Prepare payload/query -> HTTP Request -> Normalize output -> Respond to Webhook.
```

## URLs locales de referencia

- n8n local: `http://localhost:5680`
- CRM desde n8n local o Docker: `http://host.docker.internal:8082`
- `mcp-gateway` local: `http://localhost:8010`

## Resultado esperado

Si este flujo se sigue bien:

- n8n valida la integración real
- Postman da feedback rápido sobre el webhook
- `mcp-gateway` expone una tool MCP estable
- `sales-agent` consume la tool sin acoplarse al detalle del CRM
