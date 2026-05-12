from app.tools.contact_context_mock import contact_context_mock
from app.tools.echo import echo
from app.tools.contact_context import contact_context
from app.tools.appointment_availability import appointment_availability
from app.tools.appointment_events import appointment_events
from app.tools.appointment_confirm import appointment_confirm
from app.tools.appointment_reschedule import appointment_reschedule
from app.tools.appointment_cancel import appointment_cancel
from app.tools.appointment_booking_invitation import appointment_booking_invitation
from app.tools.services_search import services_search

AVAILABLE_TOOLS = [
    {
        "name": "echo",
        "description": "Devuelve el input recibido.",
    },
    {
        "name": "contact_context_mock",
        "description": "Devuelve contexto mock de un contacto para validar tool calling.",
    },
    {
        "name": "contact_context",
        "description": "Get commercial context for a contact by phone or email.",
    },
    {
        "name": "appointment_availability",
        "description": "Get appointment availability slots for a tenant, date range and optional contact.",
    },
    {
        "name": "appointment_events",
        "description": "Get appointment/calendar events for a tenant and optional contact, date range or filters.",
    },
    {
        "name": "appointment_confirm",
        "description": "Confirm an appointment through n8n for a tenant, contact and selected slot.",
    },
    {
        "name": "appointment_reschedule",
        "description": "Reschedule an existing appointment through n8n.",
    },
    {
        "name": "appointment_cancel",
        "description": "Cancel an existing appointment through n8n.",
    },
    {
        "name": "appointment_booking_invitation",
        "description": "Create a booking invitation link through n8n.",
    },
    {
        "name": "services_search",
        "description": "Search services and products in the CRM through n8n.",
    },
]
