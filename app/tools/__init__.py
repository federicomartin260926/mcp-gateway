from app.tools.contact_context_mock import contact_context_mock
from app.tools.echo import echo
from app.tools.contact_context import contact_context
from app.tools.appointment_availability import appointment_availability

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
]
