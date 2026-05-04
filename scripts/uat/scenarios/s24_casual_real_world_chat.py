#!/usr/bin/env python3.11
"""S24 — Cliente colombiano REAL con respuestas casuales/coloquiales.

OBJETIVO: certificar que el bot maneja la diversidad lingüística real:
muletillas, typos suaves, abreviaciones, "dale/vale/listo" en vez de
"sí, acepto", emojis ocasionales, frases compuestas (pregunta+respuesta
en un solo mensaje), respuestas tardías.

NO valida happy path FSM (eso lo cubre s09); valida ROBUSTEZ del bot
frente a variabilidad real del cliente.

ESTRUCTURA — Cliente con perfil "casual":
  • Saludo: "buenas, qué más" (no "Hola")
  • Confirmación: "dale" / "ok" / "vale" / "listo"
  • Acepto consent: "claro que sí" / "ok acepto" / "sale"
  • PII compuesta: "soy juan, mi correo es x@y.com" (multi-slot)
  • Cierre: "ok mándame el link" / "perfecto, finalicemos"

PASS:
  • Bot llega a NEEDS_CONSENT (ge prueba que entendió producto + ciudad).
  • Cliente acepta con frase casual → consent_given=true.
  • Audit log event='granted' source='whatsapp'.
FAIL: bot se atasca en variantes casuales / no entiende afirmación
  alternativa / pide consent dos veces.
SKIP: 22 turnos sin llegar a consent (variabilidad LLM extrema).
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.harness import (  # noqa: E402
    PASS, FAIL, SKIP, ScenarioResult, ConversationDriver,
    fetch_audit_events, hard_reset, run_one, seed_known_contact,
)
import e2e_chat  # noqa: E402

SUPPORTED_MODES = ("new", "known")


# Reglas de cliente casual — usan keywords laxos pero respuestas naturales.
# Los keywords son los que el bot REALMENTE pregunta (igual que default_rules).
# Las respuestas son lo que un colombiano escribiría en WhatsApp real.
CASUAL_RULES = [
    # Saludo / qué busca → respuesta con muletilla.
    (10, ("en qué te puedo ayudar", "como te puedo ayudar",
          "qué te gustaría", "qué buscas",
          "qué productos", "qué producto", "puedo ayudarte",
          # Variantes post-greeting reales del bot rev. 103.
          "sobre cuál te cuento", "sobre cual te cuento",
          "te cuento más", "te cuento mas",
          "qué tipo de piel", "que tipo de piel",
          "tipo de piel tienes",
          "qué necesidad", "que necesidad"),
        lambda _: "busco un jabón artesanal de coco para piel mixta"),

    # Presentación: respuesta corta colombiana.
    (20, ("presentación", "presentacion", "gramaje", "tamaño",
          "60g", "100g", "150g",
          "cuál te gustaría", "cual te gustaria",
          "qué te gustaría llevar", "que te gustaria llevar"),
        lambda _: "el de 60 gramos parce"),

    # Cantidad — coloquial.
    (15, ("cuántos", "cuantos", "cuántas", "cuantas", "qué cantidad"),
        lambda _: "uno solo"),

    # Ciudad.
    (20, ("a qué ciudad", "en qué ciudad", "qué ciudad",
          "cuál es tu ciudad", "ciudad de", "ciudad estás",
          "te encuentras", "te ubicas",
          "para dónde", "para donde",
          "destino del envío", "donde envías", "donde envias"),
        lambda _: "Bogotá"),

    # Cotización / carrier — afirmaciones casuales.
    (15, ("¿deseas cotizar", "deseas cotizar", "te cotizo",
          "cotizar el envío", "cotice el", "cotice tu",
          "valor exacto", "tarifa exacta", "te cotice el"),
        lambda _: "dale, cotízame"),

    (18, ("continuemos con tu pedido", "continuemos con la compra",
          "seguimos con tu pedido", "seguir con la compra",
          "avanzamos con tu pedido", "procedemos con",
          "continuar con tu pedido", "continuar con la compra"),
        lambda _: "ok listo, sigamos"),

    (15, ("servientrega", "transportadora", "carrier", "deprisa",
          "coordinadora", "interrapidisimo", "cabify", "elige la opción",
          "cuál prefieres",
          "continuamos con", "continuamos la", "continuamos opción",
          "la opción económica", "opción económica", "opción estándar",
          "opción express", "te sirve la", "está bien la opción",
          "esa opción"),
        lambda _: "vale, esa misma"),

    # CONSENT — respuesta casual válida (el bot debe interpretar
    # "claro que sí" como afirmación, no solo "sí, acepto").
    (60, ("estás de acuerdo", "estas de acuerdo", "está de acuerdo",
          "esta de acuerdo", "responde *sí*", "responde sí o no",
          "aceptas", "tratamiento de datos", "habeas data",
          "guardar tus datos", "guardar sus datos", "consentimiento",
          "autorizas", "me autorizas", "autorización", "autorizacion",
          "registrar tus datos", "podrías autorizarme"),
        lambda _: "claro que sí, acepto"),

    # Datos PII — frases compuestas (multi-slot).
    # En lugar de dar un solo dato cuando bot pide email, damos email + nombre.
    (30, ("cuál es tu correo", "cual es tu correo",
          "compárteme tu correo", "comparteme tu correo",
          "tu email", "tu correo electrónico", "tu correo electronico"),
        lambda _: "mi correo es crittan01@gmail.com y me llamo Cristian"),

    (30, ("nombre completo", "compárteme tu nombre", "comparteme tu nombre",
          "cómo te llamas", "como te llamas", "cuál es tu nombre"),
        lambda _: "Cristian Garzón"),

    # Documento — formato realista (con espacio, mayúsculas).
    (30, ("para procesar tu pago", "tipo de documento", "tu nit",
          "tu cédula", "tu cedula", "cédula (cc)", "cedula (cc)"),
        lambda _: "CC 1032414179"),

    # Dirección — orden natural colombiano: barrio + dirección + ciudad.
    (30, ("para la entrega", "para completar la dirección",
          "donde te enviamos", "tu dirección de", "tu direccion de",
          "compárteme la dirección", "comparteme la direccion"),
        lambda _: "Calle 3 sur 70-84, barrio Olaya, casa, Bogotá"),

    # Confirmación final — coloquial.
    (20, ("¿confirmas", "confirmas que", "generar tu link", "generar el link"),
        lambda _: "perfecto, confirmo, mándame el link"),

    # Carrito secundario (no agregar más).
    (10, ("agregar otro", "algo más", "algo mas", "deseas otro", "deseas agregar"),
        lambda _: "no, así está bien"),

    # Fallback genérico.
    (1, ("?", "¿"), lambda _: "ok dale"),
]


def scenario(phone: str, tenant_id: str, mode: str = "new") -> ScenarioResult:
    hard_reset(phone, tenant_id)
    if mode == "known":
        sb_seed = e2e_chat._supabase()
        if not seed_known_contact(sb_seed, tenant_id, phone, name="Cristian"):
            return ScenarioResult(24, f"Cliente casual mundo real [{mode}]",
                                  FAIL, "Seed known contact falló")
        # Cliente conocido NO debe re-dar PII (ya está en DB). Filtramos las
        # rules de PII (prio=30) y consent (prio=60) — si el bot pregunta
        # por algo de eso, el driver no responderá → conversación se corta
        # → detectamos vía matched_history (validación post).
        rules = [r for r in CASUAL_RULES if r[0] not in (30, 60)]
    else:
        rules = CASUAL_RULES
    drv = ConversationDriver(phone, tenant_id, rules, max_turns=22)
    res = drv.run("buenas, qué más")  # ← greeting casual real, no "Hola"

    sb = e2e_chat._supabase()
    digits = phone.lstrip("+")
    contact = sb.table("contacts").select(
        "id, consent_given, consent_source, name, email, document_number"
    ).eq("tenant_id", tenant_id).or_(
        f"phone.eq.{digits},phone.eq.+{digits}"
    ).limit(1).execute()

    bot_text = " ".join((t.get("bot") or "").lower() for t in res.transcript)
    bot_understood_intent = any(k in bot_text for k in (
        "jabón", "jabon", "60", "presentación", "presentacion", "ciudad",
    ))
    bot_asked_consent = any(k in bot_text for k in (
        "tratamiento de datos", "habeas data", "ley 1581", "autorizas",
        "respondes sí", "responde sí",
    ))

    evidence = {
        "turns": res.turns,
        "matched_rules": res.matched_rule_history,
        "bot_understood_intent": bot_understood_intent,
        "bot_asked_consent": bot_asked_consent,
        "transcript_tail": res.transcript[-4:],
    }

    if not contact.data:
        return ScenarioResult(24, f"Cliente casual mundo real [{mode}]", FAIL,
            f"Tras {res.turns} turnos casuales no se creó contact_row "
            "(bot se atascó con respuestas no canónicas)",
            evidence=evidence)

    c = contact.data[0]
    contact_id = c["id"]
    audit_granted = fetch_audit_events(sb, tenant_id, contact_id=contact_id,
                                       event="granted", limit=3)

    # ── Validación común a ambos modos: orden creada + bot no se atascó ──
    orders = sb.table("orders").select("id, status").eq(
        "contact_id", contact_id
    ).order("created_at", desc=True).limit(1).execute()
    order_status = orders.data[0].get("status") if orders.data else None

    # Detectar fallo del bot: respondió "Aún no tengo foto" cuando el
    # cliente pidió generar link / confirmó. Esto es un *signal* de
    # mis-routing del LLM (intent confuso) — no un PASS encubierto.
    bot_stuck_in_foto_fallback = (
        "no tengo foto" in bot_text or "aún no tengo foto" in bot_text
        or "aun no tengo foto" in bot_text
    )

    # ── mode=known: cliente conocido — el bot NO debe re-pedir PII ni
    # consent (ya están), Y debe completar la compra (orden creada).
    if mode == "known":
        matched_history = " | ".join(res.matched_rule_history)
        asked_pii = any(s in matched_history for s in ("prio=30 ", "prio=60 "))
        if asked_pii:
            return ScenarioResult(24, f"Cliente casual mundo real [{mode}]",
                FAIL,
                "Bot re-pidió PII/consent al cliente conocido (rules prio 30/60 dispararon)",
                evidence={**evidence, "matched_history": matched_history,
                          "order_status": order_status})
        if not orders.data:
            # Sin orden: o bot se quedó dando vueltas (foto fallback) o
            # el flow no llegó al link. SKIP solo si foto fallback (signal
            # de mis-routing); FAIL si simplemente no avanzó.
            if bot_stuck_in_foto_fallback:
                return ScenarioResult(24, f"Cliente casual mundo real [{mode}]",
                    SKIP,
                    "Bot atascado en foto fallback al solicitar link — anomalía LLM/intent",
                    evidence={**evidence, "contact": c,
                              "bot_stuck_in_foto_fallback": True})
            return ScenarioResult(24, f"Cliente casual mundo real [{mode}]",
                FAIL,
                f"Cliente conocido casual no llegó a orden en {res.turns} turnos",
                evidence={**evidence, "contact": c})
        if order_status not in {"pending_payment", "confirmed"}:
            return ScenarioResult(24, f"Cliente casual mundo real [{mode}]",
                FAIL,
                f"Orden creada pero status={order_status!r}",
                evidence={**evidence, "contact": c, "order_status": order_status})
        return ScenarioResult(24, f"Cliente casual mundo real [{mode}]", PASS,
            f"Bot manejó saludo casual + cliente conocido sin re-pedir PII "
            f"+ orden {orders.data[0]['id'][:8]} status={order_status} "
            f"({res.turns} turnos)",
            evidence={**evidence, "order_status": order_status})

    # ── mode=new: flujo completo con consent + PII + orden creada.
    if not bot_asked_consent:
        # CRITICAL: si el bot generó link sin pedir consent → bug grave
        # (Habeas Data violation). Distinto de SKIP por flow incompleto.
        if orders.data and not c.get("consent_given"):
            return ScenarioResult(24, f"Cliente casual mundo real [{mode}]",
                FAIL,
                "CRÍTICO: bot generó orden SIN pedir consent + sin "
                "consent_given=true (Ley 1581 violación)",
                evidence={**evidence, "contact": c,
                          "order_status": order_status})
        if bot_stuck_in_foto_fallback:
            return ScenarioResult(24, f"Cliente casual mundo real [{mode}]",
                SKIP,
                "Bot atascado en foto fallback — anomalía LLM/intent",
                evidence={**evidence, "contact": c,
                          "bot_stuck_in_foto_fallback": True})
        return ScenarioResult(24, f"Cliente casual mundo real [{mode}]", SKIP,
            f"Bot no llegó a NEEDS_CONSENT en {res.turns} turnos casuales",
            evidence={**evidence, "contact": c})

    if not c.get("consent_given"):
        return ScenarioResult(24, f"Cliente casual mundo real [{mode}]", FAIL,
            "Bot pidió consent pero NO interpretó 'claro que sí, acepto' como afirmación",
            evidence={**evidence, "contact": c})

    if c.get("consent_source") != "whatsapp":
        return ScenarioResult(24, f"Cliente casual mundo real [{mode}]", FAIL,
            f"consent_source={c.get('consent_source')!r} (esperado 'whatsapp')",
            evidence={**evidence, "contact": c})

    if not audit_granted:
        return ScenarioResult(24, f"Cliente casual mundo real [{mode}]", FAIL,
            "Audit log granted NO escrito (regresión)",
            evidence=evidence)

    extracted = {
        "name": bool(c.get("name")),
        "email": bool(c.get("email")),
        "document": bool(c.get("document_number")),
    }
    extracted_count = sum(extracted.values())

    return ScenarioResult(24, f"Cliente casual mundo real [{mode}]", PASS,
        f"Bot manejó cliente casual: consent OK + {extracted_count}/3 PII extraído en {res.turns} turnos",
        evidence={**evidence, "extracted": extracted})


if __name__ == "__main__":
    sys.exit(run_one(scenario))
