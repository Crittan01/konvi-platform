"""F53 — el connector WhatsApp NO debe bloquear el event loop con I/O síncrona.

El webhook DEBE ACKear 200 a Meta de inmediato (política Meta). Antes:
  - decouple_and_enqueue era `async def` → Starlette la corría EN el event loop, y
    hacía I/O síncrona pesada (persist_whatsapp_message: varios .execute() de Supabase)
    sin await → bloqueaba el loop y ningún otro webhook se aceptaba/ACKeaba.
  - las dependencias async llamaban resolvers síncronos (HTTP a Supabase/Vault) directo.

Guarda de regresión source-based (no importa el módulo, evita traer todo el stack del
connector). Espeja el estilo de los fitness-tests del repo (test_audit_*).
"""
from pathlib import Path
import re

_REPO = Path(__file__).resolve().parents[1]
_WEBHOOK = (_REPO / "services/connector-whatsapp/routers/webhook.py").read_text()
_META = (_REPO / "services/connector-whatsapp/dependencies/meta.py").read_text()


def test_decouple_and_enqueue_is_sync():
    # Background task SYNC → Starlette la ejecuta en el threadpool, no en el event loop.
    assert re.search(r"^def decouple_and_enqueue\(", _WEBHOOK, re.M), \
        "decouple_and_enqueue debe ser sync (def), no async"
    assert not re.search(r"^async def decouple_and_enqueue\(", _WEBHOOK, re.M)


def test_blocking_resolvers_go_to_threadpool():
    # Los 3 lookups síncronos (HTTP Supabase/Vault) se delegan al threadpool.
    assert "run_in_threadpool(_resolve_tenant_app_secret" in _META
    assert "run_in_threadpool(_resolve_tenant_id_for_phone_number" in _META
    assert "run_in_threadpool(_resolve_tenant_verify_token" in _WEBHOOK
