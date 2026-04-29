"""Specialist base — patrón común a todos los estados FSM.

Cada specialist concreto:
  1. Define ``state`` (el State de la FSM que maneja).
  2. Define ``build_system_instruction(ctx)`` — prompt acotado al rol del estado.
  3. Define ``tool_mode`` (``AUTO`` por default, ``ANY`` para forzar function call).
  4. Opcionalmente override ``preflight(ctx)`` para gates determinísticos
     (ej. verificar que cart no está vacío).
"""
from __future__ import annotations

import logging
from typing import Optional

from core.context import ConversationContext, TurnResult
from core.fsm import State, tools_for_state
from llm.client import invoke_llm

logger = logging.getLogger("orchestrator.specialists.base")


class BaseSpecialist:
    """Base abstracta — usar via subclase.

    Los specialists son objetos sin estado mutable. Pueden instanciarse una
    vez y reusarse a lo largo del proceso.

    NOTA: NO es ``@dataclass`` porque el ``__init__`` generado por dataclass
    sobreescribe los class-attributes (``state``, ``tool_mode``) overrideados
    en subclases con los defaults de la base. Mantenemos clase regular y los
    overrides se respetan a través del MRO.
    """

    # Override en subclase. Class attributes — las subclases los reemplazan.
    state: State = State.CATALOG_MODE
    # Modo del FunctionCalling: ``AUTO`` = LLM decide; ``ANY`` = forzar call;
    # ``NONE`` = solo texto.
    tool_mode: str = "AUTO"

    def build_system_instruction(self, ctx: ConversationContext) -> str:
        """Override en subclase para acotar el prompt al estado."""
        raise NotImplementedError

    def preflight(self, ctx: ConversationContext) -> Optional[TurnResult]:
        """Gate determinístico antes de invocar al LLM.

        Si retorna no-None, el coordinator usa ese resultado y NO invoca LLM.
        Útil para casos como "carrito vacío" en estado CATALOG_MODE — no
        gastamos tokens.
        """
        return None

    def build_contents(self, ctx: ConversationContext) -> list:
        """Construye el array ``contents`` para el SDK Gemini.

        Convención (alineada con Gemini docs sobre layout de contexto):
          - El catálogo + estado FSM van como primer turn ``user`` (cacheable
            por tenant si se habilita context caching).
          - Los últimos N mensajes van como turnos ``user``/``model`` siguientes.
          - El mensaje actual va al final como ``user``.

        Ref: https://ai.google.dev/gemini-api/docs/text-generation
        """
        contents: list[dict] = []

        # Bloque de contexto (catálogo + estado actual del cart si existe).
        ctx_lines: list[str] = [
            f"[FSM_STATE: {ctx.fsm_state.value}]",
            f"[TENANT: {ctx.tenant_name}]",
        ]

        if ctx.cart and ctx.cart.items:
            ctx_lines.append("\n[CARRITO ACTUAL]")
            for item in ctx.cart.items:
                ctx_lines.append(
                    f"  - product_id={item.product_id} variation_id={item.variation_id} "
                    f"qty={item.quantity} unit_price_cents={item.unit_price_cents}"
                )
            ctx_lines.append(f"  subtotal_cents={ctx.cart.subtotal_cents}")
            if ctx.cart.shipping_cents:
                ctx_lines.append(f"  shipping_cents={ctx.cart.shipping_cents}")
            ctx_lines.append(f"  total_cents={ctx.cart.total_cents}")

        if ctx.contact_record:
            cr = ctx.contact_record
            ctx_lines.append("\n[DATOS DEL CLIENTE EN DB]")
            ctx_lines.append(f"  consent_given={bool(cr.get('consent_given'))}")
            for f in ("name", "email", "document_type", "document_number"):
                if cr.get(f):
                    ctx_lines.append(f"  {f}={cr[f]}")
            if cr.get("address"):
                ctx_lines.append(f"  address={cr['address']}")

        if ctx.catalog:
            ctx_lines.append("\n[CATÁLOGO ACTIVO]")
            for prod in ctx.catalog[:30]:
                title = prod.get("title", "")
                desc = (prod.get("description") or "")[:200]
                ctx_lines.append(
                    f"  product_id={prod.get('id')} title={title!r} desc={desc!r}"
                )
                for v in (prod.get("variants") or [])[:8]:
                    ctx_lines.append(
                        f"    variation_id={v.get('id')} "
                        f"label={v.get('label')!r} "
                        f"price_cop={v.get('price')} stock={v.get('stock')}"
                    )

        contents.append({
            "role": "user",
            "parts": [{"text": "\n".join(ctx_lines)}],
        })

        # Historial reciente (últimos N).
        for msg in (ctx.history or [])[-12:]:
            direction = str(msg.get("direction") or "").lower()
            role = "user" if direction == "inbound" else "model"
            text = str(msg.get("content") or "")
            if not text:
                continue
            contents.append({"role": role, "parts": [{"text": text}]})

        # Mensaje actual del cliente.
        contents.append({
            "role": "user",
            "parts": [{"text": ctx.content}],
        })

        return contents

    async def run(self, ctx: ConversationContext) -> TurnResult:
        """Ejecuta el specialist:
          1. Preflight gate.
          2. invoke_llm con tools restringidos al estado.
          3. Si LLM emite function_calls → TurnResult.execute_tools.
             Si emite texto → TurnResult.text.
        """
        gate = self.preflight(ctx)
        if gate is not None:
            return gate

        system_instruction = self.build_system_instruction(ctx)
        contents = self.build_contents(ctx)
        allowed = tools_for_state(self.state)

        try:
            turn = invoke_llm(
                system_instruction=system_instruction,
                contents=contents,
                allowed_tools=allowed,
                tool_mode=self.tool_mode,
            )
        except Exception as exc:
            logger.exception("[specialist.%s] LLM invoke failed", self.state.value)
            return TurnResult.error_result(exc)

        if turn.function_calls:
            return TurnResult.execute_tools(turn.function_calls)
        if turn.text:
            return TurnResult.text(turn.text)

        # Fallback: el LLM no devolvió ni texto ni call.
        logger.warning(
            "[specialist.%s] LLM no devolvió texto ni function_calls (finish=%s)",
            self.state.value, turn.finish_reason.value,
        )
        return TurnResult.text(
            "Disculpa, no pude procesar tu mensaje. ¿Puedes intentar de nuevo?",
        )
