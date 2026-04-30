"""
Audit logging — decorator y helper para popular `audit_log` de forma uniforme.

Rev. 72 — cierra el drift D4 (audit_log existe en DB pero nadie la poblaba).

Patrón de uso (decorator opt-in):

    from dependencies.audit import audit_log

    @router.patch("/{order_id}")
    @audit_log(entity_type="order", action="status_changed")
    async def patch_order(
        order_id: str,
        patch: OrderPatch,
        request: Request,                     # <- requerido para extraer user del JWT
        tenant_id: str = Depends(get_current_tenant),
        supabase: Client = Depends(get_service_client),
        ...
    ):
        ...
        return result

Reglas:
- El handler DEBE recibir `request: Request`, `tenant_id: str` y `supabase: Client`.
- El decorator inserta a `audit_log` DESPUÉS de que el handler retorna OK.
- Si el handler lanza excepción, el audit NO se inserta (no auditamos fallos).
- Si el insert al audit_log falla, NO rompe el handler (fire-and-forget con log warning).
- `entity_id` se intenta extraer en este orden:
  1. Path param que termine en `_id` (ej. `order_id`, `contact_id`).
  2. `result['id']` o `result.id` si el handler devuelve dict/obj.
  3. None (acción sin entidad asociada — ej. bulk delete).
- `payload` es el dict resultado (snapshot de la entidad post-operación) o el body request si está disponible.

Acciones canónicas (action enum):
- `created`: POST que crea entidad nueva.
- `updated`: PATCH/PUT general.
- `deleted`: DELETE (incluye soft-delete y anonimización).
- `status_changed`: PATCH específico que cambia status.
- `connected`: integración conectada (Wompi, Envia, MeLi, Telegram).
- `disconnected`: integración desconectada.
- `role_changed`: cambio de rol de un team member.

Entity types canónicos (alineado con plan rev. 72):
- order, contact, product, variation, claim, purchase_order, supplier,
  kb_doc, settings, integration, team_member.
"""
import logging
from functools import wraps
from typing import Any, Callable, Optional

from fastapi import Request

from dependencies.auth import _extract_jwt_payload  # type: ignore

logger = logging.getLogger(__name__)


def write_audit_event(
    *,
    supabase: Any,
    tenant_id: str,
    action: str,
    entity_type: str,
    entity_id: Optional[str] = None,
    user_email: Optional[str] = None,
    user_id: Optional[str] = None,
    payload: Optional[dict] = None,
) -> None:
    """Inserta un evento en audit_log. Best-effort — falla silente con log warning.

    Use directamente cuando el decorator no aplica (ej. eventos de webhook,
    o eventos compuestos donde un handler genera múltiples efectos)."""
    try:
        supabase.table("audit_log").insert({
            "tenant_id":   tenant_id,
            "user_id":     user_id,
            "user_email":  user_email,
            "action":      action,
            "entity_type": entity_type,
            "entity_id":   str(entity_id) if entity_id is not None else None,
            "payload":     payload,
        }).execute()
    except Exception as exc:  # pragma: no cover — fire-and-forget
        logger.warning("[AUDIT] insert failed entity=%s action=%s err=%s",
                       entity_type, action, exc)


def _safe_jsonable(obj: Any) -> Any:
    """Convierte recursivamente Pydantic / objetos a dict simple para JSONB."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {k: _safe_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_safe_jsonable(x) for x in obj]
    if hasattr(obj, "model_dump"):  # pydantic v2
        try:
            return obj.model_dump(mode="json")
        except Exception:
            return None
    if hasattr(obj, "dict"):  # pydantic v1 fallback
        try:
            return obj.dict()
        except Exception:
            return None
    return None


def _extract_entity_id(kwargs: dict, result: Any) -> Optional[str]:
    """Busca entity_id (1) en path params *_id (excluyendo tenant_id/user_id),
    (2) en result['id'] o result.id."""
    for key, val in kwargs.items():
        if key in ("tenant_id", "user_id"):
            continue
        if key.endswith("_id") and val is not None:
            return str(val)
    if result is None:
        return None
    if isinstance(result, dict) and result.get("id"):
        return str(result["id"])
    if hasattr(result, "id") and getattr(result, "id"):
        return str(getattr(result, "id"))
    return None


def _extract_user_info(request: Optional[Request]) -> tuple[Optional[str], Optional[str]]:
    """Devuelve (user_id, user_email) extraídos del JWT. None si falla."""
    if request is None:
        return None, None
    try:
        payload = _extract_jwt_payload(request)
        return payload.get("sub"), payload.get("email")
    except Exception:
        return None, None


def audit_log(*, entity_type: str, action: str) -> Callable:
    """Decorator opt-in para auditar mutations de FastAPI.

    El handler decorado DEBE aceptar `request: Request`, `tenant_id`, `supabase`
    como kwargs (vía Depends). Si falta alguno el decorator no rompe pero
    advierte y omite el audit.
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            result = await func(*args, **kwargs)

            request: Optional[Request] = kwargs.get("request")
            supabase = kwargs.get("supabase")
            tenant_id = kwargs.get("tenant_id")

            if supabase is None or tenant_id is None:
                logger.warning(
                    "[AUDIT] skip — handler sin supabase/tenant_id en kwargs (entity=%s action=%s).",
                    entity_type, action,
                )
                return result

            user_id, user_email = _extract_user_info(request)
            entity_id = _extract_entity_id(kwargs, result)
            payload = _safe_jsonable(result)

            write_audit_event(
                supabase=supabase,
                tenant_id=str(tenant_id),
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                user_id=user_id,
                user_email=user_email,
                payload=payload,
            )
            return result
        return wrapper
    return decorator
