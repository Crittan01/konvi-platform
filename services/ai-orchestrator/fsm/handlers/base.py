"""State Handler base — Protocol + tipos compartidos.

Sem 1 refactor (ADR-0017). Define el contrato uniforme que cada handler
implementa para reemplazar los 13 bypasses dispersos del monolito.

Diseño:
  • `TurnInput`: estructura inmutable con los datos del turn que el
    handler puede leer. NO incluye DB client en esta fase Sem 1 (los
    handlers son funciones puras o async-puras). Si el handler necesita
    leer DB, lo hace vía helpers que reciben supabase como argumento
    explícito.
  • `HandlerResult`: lo que el handler retorna cuando RESUELVE el turn
    determinísticamente. Si retorna None, el dispatcher prueba el
    siguiente handler.
  • `StateHandler` Protocol: contrato de invocación.

Async: handlers son `async def` porque pueden necesitar DB lookups
(get_cart_with_items, etc.) o emitir cart events. El dispatcher los
invoca con `await`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, runtime_checkable


@dataclass(frozen=True)
class TurnInput:
    """Datos del turn que el handler puede leer.

    Inmutable por diseño — handlers no pueden mutar el input. Si un
    handler necesita state derivado, lo computa localmente.

    Campos:
      • inbound_text: texto del cliente (raw, sin normalizar).
      • content_type: 'text' | 'image' | 'audio' | etc.
      • display_state: resuelto por FSM resolver (línea 8655 actual).
      • contact_record: dict del contact en DB (puede estar stale —
        handlers que necesitan freshness lo recargan vía supabase).
      • cart: dict con .items (puede ser None si no hay cart abierto).
      • catalog: list de productos del tenant.
      • history: list de mensajes (≤25 por CONVERSATION_HISTORY_LIMIT).
      • conversation_id, tenant_id, contact_id, message_id: identidad.
      • buying_intent, shipping_quoted, carrier_selected: flags FSM.
      • supabase: cliente Supabase (necesario para handlers que persisten
        o re-leen). NO se usa para mutar TurnInput (es inmutable).
    """
    # Identidad
    conversation_id: str
    tenant_id: str
    message_id: str
    contact_id: Optional[str] = None

    # Inbound
    inbound_text: str = ""
    content_type: str = "text"

    # Estado FSM
    display_state: str = "CATALOG_MODE"
    buying_intent: bool = False
    shipping_quoted: bool = False
    carrier_selected: bool = False
    order_confirm_pending: bool = False

    # Datos cargados
    contact_record: dict = field(default_factory=dict)
    cart: Optional[dict] = None
    catalog: list = field(default_factory=list)
    history: list = field(default_factory=list)

    # Side-channels (acceso controlado)
    supabase: Any = None  # supabase.Client — Any para evitar import en tipos

    # Metadata adicional (extensible sin romper handlers existentes)
    extras: dict = field(default_factory=dict)


@dataclass(frozen=True)
class HandlerResult:
    """Output de un handler cuando resuelve determinísticamente el turn.

    Campos:
      • outbound_text: texto a enviar al cliente.
      • handler_name: nombre del handler (para audit log + logging).
      • mark_processed: marcar mensaje como processed tras emitir
        (default True; un handler que solo enriquece state puede usar
        False).
      • short_circuit: si True, el dispatcher detiene el pipeline tras
        este handler (default True). Permite "pre-handlers" no
        terminales en versiones futuras.
      • emit_events: lista de cart_events a emitir antes de retornar
        (e.g. summary_rendered, payment_link_created). Cada item es un
        dict con shape libre — el caller decide cómo persistirlos.
      • log_extras: dict con metadata extra para el logger.info de
        cierre del handler.
    """
    outbound_text: str
    handler_name: str
    mark_processed: bool = True
    short_circuit: bool = True
    emit_events: list = field(default_factory=list)
    log_extras: dict = field(default_factory=dict)


@runtime_checkable
class StateHandler(Protocol):
    """Contrato uniforme para todos los handlers de estado.

    Cada handler:
      1. Recibe TurnInput inmutable.
      2. Decide si aplica a este turn (lógica interna).
      3. Si aplica → retorna HandlerResult.
      4. Si NO aplica → retorna None (dispatcher prueba siguiente).

    Implementaciones concretas viven en `fsm/handlers/<state>.py`.
    """

    # Estados a los que el handler responde. El dispatcher solo invoca
    # handlers cuyo `applies_to_states` contiene `turn.display_state`.
    applies_to_states: frozenset[str]

    # Prioridad dentro del mismo estado. Menor número = corre antes.
    # Default 100. Handlers que "atajan" (e.g. correction intent dentro
    # de READY_FOR_SUMMARY) usan prioridad < 50 para correr ANTES del
    # render de resumen.
    priority: int

    # Nombre canónico para logging y testing. Debe ser único.
    name: str

    async def handle(self, turn: TurnInput) -> Optional[HandlerResult]:
        """Decide si aplica y retorna HandlerResult o None.

        IMPORTANTE: este método NO emite outbound directamente ni marca
        message processed. Solo retorna el HandlerResult; el caller
        (dispatcher consumer) ejecuta los side-effects.
        """
        ...
