from app.tools.contact_context_mock import contact_context_mock
from app.tools.echo import echo

AVAILABLE_TOOLS = [
    {
        "name": "echo",
        "description": "Devuelve el input recibido.",
    },
    {
        "name": "contact_context_mock",
        "description": "Devuelve contexto mock de un contacto para validar tool calling.",
    },
]
