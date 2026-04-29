"""Coordinator — router central del orquestador conversacional.

Responsabilidad:
  1. Carga el estado actual de la conversación (cart, contact, history,
     catalog, KB) y construye :class:`ConversationContext`.
  2. Determina el estado FSM via :func:`core.fsm.determine_state`.
  3. Despacha al :class:`BaseSpecialist` correspondiente.
  4. Si el specialist emite ``EXECUTE_TOOLS``, ejecuta los handlers
     registrados en :mod:`tools_v2.registry`, alimenta los resultados de
     vuelta al LLM como ``function_response`` y reinvoca al specialist
     hasta obtener texto final (con cap de iteraciones).
  5. Persiste el outbound y aplica side-effects (escalation, etc.).

NO contiene reglas de negocio específicas de un estado — eso vive en los
specialists. NO contiene lógica del FSM — eso vive en :mod:`core.fsm`.

Coherente con el patrón Supervisor/Coordinator de LangGraph:
  https://langchain-ai.github.io/langgraph/tutorials/multi_agent/agent_supervisor/
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from supabase import Client

from core.context import ConversationContext, TurnDecisionKind, TurnResult
from core.fsm import State, determine_state, FsmFacts
from llm.client import invoke_llm
from llm.parsers import FunctionCall
from persistence.carts_repo import CartsRepo
from specialists.concrete import get_specialist
from tools_v2.registry import get_handler

logger = logging.getLogger("orchestrator.core.coordinator")


# Cap de iteraciones cuando el LLM hace múltiples function_calls encadenados.
# Doc oficial Gemini no fija un límite duro — 5 cubre los flujos reales.
_MAX_TOOL_ITERATIONS = 5


def _facts_from_cart_and_contact(
    *, cart: Any, contact: dict, last_outbound_consent: bool,
    last_outbound_confirm: bool,
) -> FsmFacts:
    """Materializa hechos para la FSM desde cart + contact_record."""
    has_items = bool(cart and getattr(cart, "items", None))
    sm = (getattr(cart, "shipping_meta", None) or {}) if cart else {}
    rates = sm.get("rates") or []
    shipping_quoted = bool(rates)
    selected = sm.get("selected_carrier") or {}
    carrier_selected = bool(selected.get("carrier") or selected.get("tag"))

    addr = contact.get("address") or {}
    btype = str(addr.get("building_type") or "").lower()
    has_addr = bool(
        addr.get("street") and addr.get("city") and btype
        and (btype != "edificio" or addr.get("apartment"))
        and (btype != "conjunto" or (addr.get("apartment") and addr.get("tower")))
    )

    return FsmFacts(
        has_cart_with_items=has_items,
        shipping_quoted=shipping_quoted,
        carrier_selected=carrier_selected,
        consent_given=bool(contact.get("consent_given")),
        has_email=bool(contact.get("email")),
        has_name=bool(contact.get("name")),
        has_document=bool(contact.get("document_type") and contact.get("document_number")),
        has_complete_address=has_addr,
        last_outbound_was_summary_question=False,
        last_outbound_was_order_confirm_question=last_outbound_confirm,
    )


class Coordinator:
    """Punto de entrada del orquestador v2.

    Uso desde el worker::

        coord = Coordinator(supabase=sb)
        await coord.handle_inbound_message(
            tenant_id=..., conversation_id=..., message_id=...,
            content=..., content_type="text", customer_phone=...,
        )
    """

    def __init__(self, supabase: Client):
        self._sb = supabase
        self._carts_repo = CartsRepo(supabase)

    async def handle_inbound_message(
        self,
        *,
        tenant_id: str,
        conversation_id: str,
        message_id: str,
        content: str,
        content_type: str,
        customer_phone: str,
        # Inyectables — el coordinator delega la carga a helpers existentes
        # del orchestrator viejo durante la migración Strangler Fig.
        load_catalog,           # async (tenant_id) -> list[dict]
        load_kb_text,           # async (tenant_id, query) -> str
        load_history,           # async (conversation_id) -> list[dict]
        load_contact,           # (tenant_id, phone) -> tuple[id, dict]
        load_tenant_meta,       # (tenant_id) -> dict
        send_outbound_text,     # async (conv_id, tenant_id, text)
        send_outbound_image,    # async (conv_id, tenant_id, url, caption)
        mark_processed,         # (msg_id, status, skip_reason?) callable
        set_human_takeover,     # (conv_id) callable
    ) -> None:
        """Procesa un único inbound. Idempotente: si falla a media transacción
        el mensaje queda en ``processing`` y el sweep del worker lo retoma.
        """
        try:
            # 1. Cargar contexto (catalog + KB en paralelo). Cart sync.
            import asyncio
            catalog, kb_text, history = await asyncio.gather(
                load_catalog(tenant_id),
                load_kb_text(tenant_id, content),
                load_history(conversation_id),
            )
            contact_id, contact_record = load_contact(tenant_id, customer_phone)
            tenant_meta = load_tenant_meta(tenant_id)
            cart = self._carts_repo.get_open_cart(
                tenant_id=tenant_id, conversation_id=conversation_id,
            )

            # 2. Construir hechos FSM y determinar estado.
            last_oc_consent = self._last_outbound_matched(
                history, ["nos autorizas", "me autorizas"],
            )
            last_oc_confirm = self._last_outbound_matched(
                history, ["confirmas que armamos", "armamos el pedido"],
            )
            facts = _facts_from_cart_and_contact(
                cart=cart, contact=contact_record,
                last_outbound_consent=last_oc_consent,
                last_outbound_confirm=last_oc_confirm,
            )
            state = determine_state(facts)

            ctx = ConversationContext(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                message_id=message_id,
                contact_id=contact_id,
                customer_phone=customer_phone,
                content=content,
                content_type=content_type,
                fsm_state=state,
                cart=cart,
                contact_record=contact_record or {},
                history=history or [],
                catalog=catalog or [],
                kb_text=kb_text or "",
                tenant_name=tenant_meta.get("name", ""),
                tenant_tono=tenant_meta.get("tono", "amigable"),
                tenant_escalation_role=tenant_meta.get("escalation_role", "asesor"),
                ai_agent=tenant_meta.get("ai_agent") or {},
                is_first_outbound_in_conversation=not any(
                    str(m.get("direction") or "").lower() == "outbound"
                    for m in (history or [])
                ),
                last_outbound_was_consent_question=last_oc_consent,
                last_outbound_was_order_confirm_question=last_oc_confirm,
            )

            logger.info(
                "[coord] tenant=%s conv=%s state=%s cart_items=%d",
                tenant_id, conversation_id, state.value,
                len(cart.items) if cart and cart.items else 0,
            )

            # 3. Ejecutar specialist + bucle de tools.
            result = await self._run_specialist_with_tools(ctx)

            # 4. Aplicar efectos.
            await self._apply_result(
                ctx=ctx,
                result=result,
                send_outbound_text=send_outbound_text,
                send_outbound_image=send_outbound_image,
                set_human_takeover=set_human_takeover,
            )

            mark_processed(message_id, "processed", None)

        except Exception:
            logger.exception(
                "[coord] failure handling msg=%s conv=%s",
                message_id, conversation_id,
            )
            mark_processed(message_id, "failed", "coordinator_exception")

    # ── Internals ────────────────────────────────────────────────────────

    async def _run_specialist_with_tools(
        self, ctx: ConversationContext,
    ) -> TurnResult:
        """Bucle: specialist → ejecutar tools → feed resultados al LLM →
        repetir hasta texto o cap de iteraciones.
        """
        specialist = get_specialist(ctx.fsm_state)
        result = await specialist.run(ctx)

        for iteration in range(_MAX_TOOL_ITERATIONS):
            if result.kind != TurnDecisionKind.EXECUTE_TOOLS:
                return result

            tool_results = await self._execute_tool_calls(ctx, result.tool_calls)

            # Si algún tool emitió response_text directo (ej. confirm_order →
            # mensaje con checkout URL), enviar ese texto como respuesta final
            # sin reinvocar al LLM.
            for tc, tr in zip(result.tool_calls, tool_results):
                if isinstance(tr, dict) and tr.get("response_text"):
                    return TurnResult.text(tr["response_text"])
                if tc.name == "render_summary" and isinstance(tr, dict) and tr.get("summary_text"):
                    return TurnResult.text(tr["summary_text"])
                if tc.name == "escalate_to_human" and isinstance(tr, dict) and tr.get("ok"):
                    return TurnResult.escalate(
                        reason=str(tr.get("reason") or "escalated"),
                        message=(
                            f"Te conecto con un {ctx.tenant_escalation_role}. "
                            "En un momento te atienden."
                        ),
                    )

            # Re-invocar LLM con los function_responses adjuntos.
            result = await self._reinvoke_llm_with_results(
                ctx, specialist, result.tool_calls, tool_results,
            )

        # Cap alcanzado — degradar a texto neutral.
        logger.warning("[coord] tool_iteration cap reached for conv=%s", ctx.conversation_id)
        return TurnResult.text(
            "Disculpa, tuve un problema procesando tu solicitud. ¿Puedes repetirla?",
        )

    async def _execute_tool_calls(
        self,
        ctx: ConversationContext,
        calls: list[FunctionCall],
    ) -> list[dict]:
        results: list[dict] = []
        for fc in calls:
            handler = get_handler(fc.name)
            if not handler:
                logger.warning("[coord] tool sin handler: %s", fc.name)
                results.append({"ok": False, "error": "tool_not_implemented"})
                continue
            # Inspección de la firma del handler para pasar SOLO los kwargs
            # que acepta. Más limpio que catch-TypeError encadenado.
            import inspect
            sig = inspect.signature(handler)
            params = sig.parameters
            kwargs: dict = {"ctx": ctx, "args": fc.args or {}}
            if "repo" in params:
                kwargs["repo"] = self._carts_repo
            if "supabase" in params:
                kwargs["supabase"] = self._sb
            try:
                result = await handler(**kwargs)
            except Exception as exc:
                logger.exception("[coord] tool '%s' execution failed", fc.name)
                result = {"ok": False, "error": str(exc)}
            results.append(result if isinstance(result, dict) else {"ok": True, "value": result})
            if isinstance(result, dict):
                ok = result.get("ok")
                if ok is False:
                    logger.warning(
                        "[coord] tool=%s ok=False detail=%s",
                        fc.name, {k: v for k, v in result.items() if k != "ok"},
                    )
                else:
                    logger.info("[coord] tool=%s ok=%s", fc.name, ok)
            else:
                logger.info("[coord] tool=%s value-only", fc.name)
        return results

    async def _reinvoke_llm_with_results(
        self,
        ctx: ConversationContext,
        specialist,
        prior_calls: list[FunctionCall],
        prior_results: list[dict],
    ) -> TurnResult:
        """Construye un nuevo turn con los ``function_response`` y reinvoca."""
        from core.fsm import tools_for_state

        contents = specialist.build_contents(ctx)
        # Adjuntar function_call + function_response como turnos del modelo y user.
        # El SDK ``google-genai`` acepta el formato:
        #   {"role": "model", "parts": [{"function_call": {...}}]}
        #   {"role": "user",  "parts": [{"function_response": {"name": ..., "response": {...}}}]}
        for fc, tr in zip(prior_calls, prior_results):
            contents.append({
                "role": "model",
                "parts": [{"function_call": {"name": fc.name, "args": fc.args}}],
            })
            contents.append({
                "role": "user",
                "parts": [{"function_response": {"name": fc.name, "response": tr}}],
            })

        try:
            # Tras ejecutar tools, usar AUTO en la re-invocación. Si dejamos
            # mode=ANY el modelo entra en bucle (siempre obligado a llamar
            # tool, aunque ya haya logrado lo que el cliente pidió). AUTO
            # permite que emita el texto de confirmación al cliente.
            # Ref: https://ai.google.dev/gemini-api/docs/function-calling
            turn = invoke_llm(
                system_instruction=specialist.build_system_instruction(ctx),
                contents=contents,
                allowed_tools=tools_for_state(ctx.fsm_state),
                tool_mode="AUTO",
            )
        except Exception as exc:
            logger.exception("[coord] reinvoke failed")
            return TurnResult.error_result(exc)

        if turn.function_calls:
            return TurnResult.execute_tools(turn.function_calls)
        if turn.text:
            return TurnResult.text(turn.text)
        return TurnResult.text(
            "Listo. ¿En qué más te ayudo?",
        )

    async def _apply_result(
        self,
        *,
        ctx: ConversationContext,
        result: TurnResult,
        send_outbound_text,
        send_outbound_image,
        set_human_takeover,
    ) -> None:
        if result.kind == TurnDecisionKind.SKIP:
            logger.info("[coord] skip: %s", result.skip_reason)
            return

        if result.kind == TurnDecisionKind.ERROR:
            logger.error("[coord] error result: %s", result.error)
            await send_outbound_text(
                ctx.conversation_id, ctx.tenant_id,
                "Disculpa, tuve un problema. ¿Puedes intentar de nuevo?",
            )
            return

        if result.kind == TurnDecisionKind.SEND_IMAGE and result.image_url:
            await send_outbound_image(
                ctx.conversation_id, ctx.tenant_id,
                result.image_url, result.image_caption,
            )
            return

        if result.text:
            await send_outbound_text(
                ctx.conversation_id, ctx.tenant_id, result.text,
            )

        if result.kind == TurnDecisionKind.ESCALATE:
            set_human_takeover(ctx.conversation_id)
            logger.info(
                "[coord] escalated conv=%s reason=%s",
                ctx.conversation_id, result.escalation_reason,
            )

    @staticmethod
    def _last_outbound_matched(
        history: Optional[list[dict]], markers: list[str],
    ) -> bool:
        for msg in reversed(history or []):
            if str(msg.get("direction") or "").lower() != "outbound":
                continue
            content = str(msg.get("content") or "").lower()
            return any(m in content for m in markers)
        return False
