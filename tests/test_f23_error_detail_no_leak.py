"""F23 — las respuestas de error NO filtran detalle interno al cliente.

Antes varios handlers ponían str(exc)/{e}/{body} del proveedor (APIError PostgREST,
response body de MeLi) en el `detail` de la HTTPException → info interna expuesta al
cliente. Ahora el detalle interno va SOLO al logger; el cliente recibe un mensaje
genérico accionable.

Guard source-level (mismo patrón que test_rev103_delete_contact_audit): falla si
alguien reintroduce una interpolación de excepción/response-body en un `detail=`.
"""
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ROUTERS = REPO / "services" / "api" / "routers"

# Patrones de fuga: str(exc) directo, o interpolación de la excepción/body en detail=.
_LEAK_PATTERNS = [
    re.compile(r'detail\s*=\s*str\(exc\)'),
    re.compile(r'detail\s*=\s*f"[^"]*\{e\}'),
    re.compile(r'detail\s*=\s*f"[^"]*\{exc\}'),
    re.compile(r'detail\s*=\s*f"[^"]*\{get_body\}'),
    re.compile(r'detail\s*=\s*f"[^"]*\{put_body\}'),
    re.compile(r'detail\s*=\s*f"[^"]*\{str\(e\)\}'),
]

# Archivos endurecidos en F23.
_FILES = ["mfa.py", "orders.py", "marketplace.py"]


class NoInternalErrorLeakTests(unittest.TestCase):
    def test_no_exception_detail_leak_in_hardened_routers(self):
        for fname in _FILES:
            src = (ROUTERS / fname).read_text()
            for pat in _LEAK_PATTERNS:
                m = pat.search(src)
                self.assertIsNone(
                    m,
                    f"{fname}: fuga de detalle interno reintroducida en un detail= "
                    f"(patrón {pat.pattern!r}, match {m.group(0) if m else None!r}). "
                    f"El detalle interno va al logger; el cliente recibe mensaje genérico.",
                )


if __name__ == "__main__":
    unittest.main()
