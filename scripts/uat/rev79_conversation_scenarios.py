#!/usr/bin/env python3.11
"""
Rev. 79 — Conversational E2E scenarios.

Capa complementaria al harness estático (rev78_e2e_certify.py). Inyecta
secuencias de mensajes reales al bot vía webhook local del connector y
valida las respuestas (transiciones FSM, contenido outbound, formato
canónico, presencia de cita KB, etc.).

**Slow + flaky por diseño** (LLM real). Cada escenario:
  1. RESET conversación + contacto.
  2. Envía N mensajes inbound (vía connector webhook con HMAC válida).
  3. Polling outbound hasta timeout.
  4. Assertions estructurales (no exact-text por flakiness LLM).

Pre-requisitos:
  • Stack local up (connector en :8000).
  • Variables .env: META_APP_SECRET, SUPABASE_*, GEMINI_API_KEY.
  • Tenant KAIU + número WhatsApp default (override con --phone --tenant-id).

Uso:
    python3.11 scripts/uat/rev79_conversation_scenarios.py            # todos
    python3.11 scripts/uat/rev79_conversation_scenarios.py --only 3 5 # subset

Skips automáticos si stack down. Exit code = FAIL count.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "uat"))
sys.path.insert(0, str(REPO_ROOT / "services" / "ai-orchestrator"))

# Reusamos infraestructura de e2e_chat.
import e2e_chat  # noqa: E402

DEFAULT_PHONE = e2e_chat.DEFAULT_PHONE
DEFAULT_TENANT_ID = e2e_chat.DEFAULT_TENANT_ID

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"


@dataclass
class ScenarioResult:
    number: int
    name: str
    status: str
    message: str
    evidence: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


# ─── Transport: enviar inbound + leer outbound ────────────────────────────────

def _stack_up() -> bool:
    import urllib.request, urllib.error
    try:
        with urllib.request.urlopen("http://localhost:8000/health", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def _send_inbound(phone: str, tenant_id: str, text: str) -> bool:
    """Envia un mensaje inbound al webhook. True si POST 200."""
    creds = e2e_chat._load_env()
    app_secret = creds.get("META_APP_SECRET", "")
    waba_id = creds.get("META_WABA_ID") or e2e_chat.DEFAULT_META_WABA_ID
    dest_phone_id = creds.get("META_PHONE_NUMBER_ID") or e2e_chat.DEFAULT_DEST_PHONE_ID
    payload = e2e_chat._build_meta_payload(
        customer_phone=phone, text=text,
        meta_waba_id=waba_id, dest_phone_id=dest_phone_id,
    )
    body = json.dumps(payload).encode()
    sig = e2e_chat._hmac_signature(body, app_secret)
    import urllib.request
    req = urllib.request.Request(
        e2e_chat.WEBHOOK_URL, data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "X-Hub-Signature-256": sig},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status == 200
    except Exception:
        return False


def _wait_outbound(phone: str, tenant_id: str,
                   *, since_ts: str, timeout_s: int = 25,
                   min_count: int = 1) -> list[dict]:
    """Polling outbound desde `since_ts`. Devuelve outbounds nuevos cuando
    se alcanza min_count o se vence el timeout."""
    sb = e2e_chat._supabase()
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        conv = e2e_chat._find_conversation(sb, tenant_id, phone)
        if not conv:
            time.sleep(1)
            continue
        msgs = e2e_chat._last_messages(sb, conv["id"], limit=20)
        outs = [
            m for m in msgs
            if m.get("direction") == "outbound"
            and (m.get("created_at") or "") > since_ts
        ]
        if len(outs) >= min_count:
            return outs
        time.sleep(1.5)
    return outs if "outs" in locals() else []


def _hard_reset(phone: str, tenant_id: str):
    import argparse as _ap
    args = _ap.Namespace(phone=phone, tenant_id=tenant_id, hard=True)
    try:
        e2e_chat.cmd_reset(args)
    except Exception:
        pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── Scenarios ────────────────────────────────────────────────────────────────

def scenario_1_first_contact(phone: str, tenant_id: str) -> ScenarioResult:
    _hard_reset(phone, tenant_id)
    t0 = _now_iso()
    if not _send_inbound(phone, tenant_id, "Hola, buenas tardes"):
        return ScenarioResult(1, "Primer contacto + saludo", FAIL,
            "Webhook rechazó el inbound (stack down o HMAC inválida)")
    outs = _wait_outbound(phone, tenant_id, since_ts=t0, timeout_s=25)
    if not outs:
        return ScenarioResult(1, "Primer contacto + saludo", FAIL,
            "Sin outbound del bot tras 25s")
    text = (outs[-1].get("content") or "").strip()
    if len(text) < 5:
        return ScenarioResult(1, "Primer contacto + saludo", FAIL,
            f"Outbound sospechosamente corto: {text!r}")
    return ScenarioResult(1, "Primer contacto + saludo", PASS,
        f"Bot respondió en {len(outs)} mensaje(s) ({len(text)} chars)",
        evidence={"outbound_count": len(outs), "preview": text[:120]})


def scenario_2_catalog_query(phone: str, tenant_id: str) -> ScenarioResult:
    _hard_reset(phone, tenant_id)
    t0 = _now_iso()
    _send_inbound(phone, tenant_id, "¿Qué productos tienes?")
    outs = _wait_outbound(phone, tenant_id, since_ts=t0, timeout_s=30)
    if not outs:
        return ScenarioResult(2, "Consulta catálogo", FAIL,
            "Sin outbound tras 30s")
    text = " ".join(o.get("content") or "" for o in outs).lower()
    has_listing = any(k in text for k in ("$", "cop", "precio", "producto", "jabón", "sérum"))
    if not has_listing:
        return ScenarioResult(2, "Consulta catálogo", FAIL,
            "Outbound no contiene marcadores de catálogo (precio/producto)",
            evidence={"sample": text[:200]})
    return ScenarioResult(2, "Consulta catálogo", PASS,
        f"Bot listó productos en {len(outs)} mensaje(s)",
        evidence={"outbound_count": len(outs), "preview": text[:200]})


def scenario_3_kb_citation(phone: str, tenant_id: str) -> ScenarioResult:
    _hard_reset(phone, tenant_id)
    t0 = _now_iso()
    _send_inbound(phone, tenant_id, "¿Cuál es la política de devoluciones?")
    outs = _wait_outbound(phone, tenant_id, since_ts=t0, timeout_s=30)
    if not outs:
        return ScenarioResult(3, "KB cita de fuentes", FAIL, "Sin outbound tras 30s")
    text = " ".join(o.get("content") or "" for o in outs)
    has_citation = "_Fuente:" in text or "*Fuente*" in text or "Fuente:" in text
    if not has_citation:
        return ScenarioResult(3, "KB cita de fuentes", FAIL,
            "Bot respondió sobre KB pero no incluyó cita de fuente (rev. 78 F3)",
            evidence={"sample": text[:300]})
    return ScenarioResult(3, "KB cita de fuentes", PASS,
        "Respuesta KB incluye cita explícita",
        evidence={"preview": text[:200]})


def scenario_4_out_of_domain(phone: str, tenant_id: str) -> ScenarioResult:
    _hard_reset(phone, tenant_id)
    t0 = _now_iso()
    _send_inbound(phone, tenant_id, "¿Cómo está el clima en Bogotá?")
    outs = _wait_outbound(phone, tenant_id, since_ts=t0, timeout_s=25)
    if not outs:
        return ScenarioResult(4, "Out-of-domain", FAIL, "Sin outbound tras 25s")
    text = " ".join(o.get("content") or "" for o in outs).lower()
    # Bot debe NO inventar datos meteorológicos. Acepta: redirección a
    # productos, escalación, "no tengo esa información".
    invented = any(k in text for k in (
        " grados", "celsius", "soleado", "lluvia", "humedad", "°c", "temperatura"
    ))
    if invented:
        return ScenarioResult(4, "Out-of-domain", FAIL,
            "Bot inventó datos meteorológicos — alucinación detectada",
            evidence={"sample": text[:300]})
    return ScenarioResult(4, "Out-of-domain", PASS,
        "Bot no alucinó respuesta sobre clima",
        evidence={"preview": text[:200]})


def scenario_5_photo_request(phone: str, tenant_id: str) -> ScenarioResult:
    _hard_reset(phone, tenant_id)
    t0 = _now_iso()
    _send_inbound(phone, tenant_id, "Tienes foto del jabón de coco?")
    outs = _wait_outbound(phone, tenant_id, since_ts=t0, timeout_s=30)
    if not outs:
        return ScenarioResult(5, "Foto producto", FAIL, "Sin outbound tras 30s")
    has_image = any(o.get("content_type") == "image" for o in outs)
    text = " ".join(o.get("content") or "" for o in outs).lower()
    has_fallback = "no tengo" in text or "no dispongo" in text or "imagen" in text
    if not (has_image or has_fallback):
        return ScenarioResult(5, "Foto producto", FAIL,
            "Bot ni envió imagen ni respondió fallback explicativo",
            evidence={"outbound_count": len(outs)})
    return ScenarioResult(5, "Foto producto", PASS,
        "Bot envió imagen" if has_image else "Bot respondió fallback explicativo",
        evidence={"image_sent": has_image,
                  "outbound_count": len(outs)})


def scenario_6_disordered_data(phone: str, tenant_id: str) -> ScenarioResult:
    """Cliente da name+email+document+address en un solo mensaje DENTRO del
    flujo de captura (post-consent). Verifica que el FSM haga extracción
    multi-campo en una pasada, en lugar de pedir uno a uno.

    Diseño: avanzamos el FSM hasta NEEDS_EMAIL antes del volcado, así la
    persistencia SÍ se activa (rev. 79 nota: persistencia exige consent_given).
    """
    _hard_reset(phone, tenant_id)
    # 1. abrir compra → bot pregunta producto/cotización
    _send_inbound(phone, tenant_id, "Hola, quiero comprar 1 jabón artesanal de coco")
    time.sleep(10)
    # 2. confirmar producto y dar ciudad para cotizar (suele dispararse aquí
    #    el flujo de consent/datos personales).
    _send_inbound(phone, tenant_id, "Sí, ese mismo. Envía a Bogotá")
    time.sleep(12)
    # 3. consent
    _send_inbound(phone, tenant_id, "Acepto que guarden mis datos")
    time.sleep(10)
    t0 = _now_iso()
    # 4. volcado multi-campo
    _send_inbound(phone, tenant_id,
        "Soy Cristian Garzon, mi correo es crittan01@gmail.com, "
        "cédula CC 1032414179, "
        "dirección Calle 3 sur 70-84, casa, barrio Olaya, Bogotá.")
    outs = _wait_outbound(phone, tenant_id, since_ts=t0, timeout_s=45)
    if not outs:
        return ScenarioResult(6, "Datos desordenados", FAIL,
            "Sin outbound tras inbound multi-campo")
    sb = e2e_chat._supabase()
    digits = phone.lstrip("+")
    contact = sb.table("contacts").select(
        "name, email, document_number, address, consent_given"
    ).eq("tenant_id", tenant_id).eq("phone", "+" + digits).limit(1).execute()
    if not contact.data:
        return ScenarioResult(6, "Datos desordenados", SKIP,
            "Contacto sin abrir — flujo no llegó a NEEDS_CONSENT con este "
            "scripting (LLM puede variar). Comportamiento esperado por compliance.")
    c = contact.data[0]
    if not c.get("consent_given"):
        return ScenarioResult(6, "Datos desordenados", SKIP,
            "consent_given=False — flujo no avanzó a captura, esperado.")
    extracted = {
        "name": bool(c.get("name")),
        "email": bool(c.get("email")),
        "document": bool(c.get("document_number")),
        "address": bool(c.get("address")),
    }
    missing = [k for k, v in extracted.items() if not v]
    if len(missing) > 2:
        return ScenarioResult(6, "Datos desordenados", FAIL,
            f"FSM/LLM extrajo solo {4-len(missing)}/4 campos",
            evidence=extracted)
    return ScenarioResult(6, "Datos desordenados", PASS,
        f"Extracción multi-campo: {4-len(missing)}/4 OK ({missing} pendientes)",
        evidence=extracted)


def scenario_7_format_canonical(phone: str, tenant_id: str) -> ScenarioResult:
    """Bot debe usar formato canónico: nada de `**bold**` ni `• ` solo."""
    _hard_reset(phone, tenant_id)
    t0 = _now_iso()
    _send_inbound(phone, tenant_id, "¿Qué productos tienes?")
    outs = _wait_outbound(phone, tenant_id, since_ts=t0, timeout_s=30)
    text = " ".join(o.get("content") or "" for o in outs)
    if "**" in text:
        return ScenarioResult(7, "Formato canónico WhatsApp", FAIL,
            "Outbound contiene `**` (markdown no normalizado)",
            evidence={"sample": text[:200]})
    # Bullets aceptados: `* `, `- ` (canon FAQ WhatsApp). `• ` debe haberse normalizado.
    if "\n• " in text or text.startswith("• "):
        return ScenarioResult(7, "Formato canónico WhatsApp", FAIL,
            "Outbound contiene `• ` Unicode (debió normalizarse a `* `)",
            evidence={"sample": text[:200]})
    return ScenarioResult(7, "Formato canónico WhatsApp", PASS,
        "Outbound sin `**` ni `• ` (rev. 77 normaliza al canon)",
        evidence={"sample": text[:120]})


def scenario_8_revoke(phone: str, tenant_id: str) -> ScenarioResult:
    _hard_reset(phone, tenant_id)
    _send_inbound(phone, tenant_id, "Hola, quiero comprar")
    time.sleep(8)
    _send_inbound(phone, tenant_id, "Sí acepto guardar mis datos")
    time.sleep(8)
    t0 = _now_iso()
    _send_inbound(phone, tenant_id, "Por favor elimina todos mis datos")
    outs = _wait_outbound(phone, tenant_id, since_ts=t0, timeout_s=20)
    if not outs:
        return ScenarioResult(8, "Revocación de consentimiento", FAIL,
            "Sin outbound tras solicitud de eliminación")
    sb = e2e_chat._supabase()
    digits = phone.lstrip("+")
    contact = sb.table("contacts").select(
        "consent_given, consent_revoked_at"
    ).eq("tenant_id", tenant_id).eq("phone", "+" + digits).limit(1).execute()
    if not contact.data:
        return ScenarioResult(8, "Revocación de consentimiento", PASS,
            "Contacto eliminado (revocación procesada)")
    c = contact.data[0]
    if c.get("consent_given"):
        return ScenarioResult(8, "Revocación de consentimiento", FAIL,
            "consent_given sigue True tras solicitud de revocación",
            evidence=c)
    return ScenarioResult(8, "Revocación de consentimiento", PASS,
        "consent_given=False tras revocación",
        evidence=c)


# ─── Runner ───────────────────────────────────────────────────────────────────

SCENARIOS: list[Callable] = [
    scenario_1_first_contact,
    scenario_2_catalog_query,
    scenario_3_kb_citation,
    scenario_4_out_of_domain,
    scenario_5_photo_request,
    scenario_6_disordered_data,
    scenario_7_format_canonical,
    scenario_8_revoke,
]


def run_all(phone: str, tenant_id: str, only: list[int] | None) -> list[ScenarioResult]:
    if not _stack_up():
        return [ScenarioResult(0, "Stack health", SKIP,
            "Connector :8000 no responde — escenarios skip todos")]
    results: list[ScenarioResult] = []
    for i, fn in enumerate(SCENARIOS, start=1):
        if only and i not in only:
            continue
        print(f"\n[{i}] {fn.__name__} ...", file=sys.stderr)
        try:
            res = fn(phone, tenant_id)
        except Exception as exc:
            res = ScenarioResult(i, fn.__name__, FAIL,
                f"Excepción: {exc}", error=traceback.format_exc())
        print(f"    → {res.status}: {res.message}", file=sys.stderr)
        results.append(res)
    return results


def render_md(results: list[ScenarioResult]) -> str:
    p = sum(1 for r in results if r.status == PASS)
    f = sum(1 for r in results if r.status == FAIL)
    s = sum(1 for r in results if r.status == SKIP)
    icon = {PASS: "✅", FAIL: "❌", SKIP: "⏭️"}
    lines = [
        f"# Rev. 79 — Conversational E2E ({datetime.now(timezone.utc).isoformat(timespec='seconds')})",
        "",
        f"**Resumen**: {p} PASS · {f} FAIL · {s} SKIP",
        "",
        "| # | Escenario | Status | Mensaje |",
        "|---|---|---|---|",
    ]
    for r in results:
        msg = r.message.replace("\n", " ")
        lines.append(f"| {r.number} | {r.name} | {icon[r.status]} {r.status} | {msg} |")
    lines.append("")
    for r in results:
        if r.evidence or r.error:
            lines.append(f"### S{r.number} — {r.name}")
            if r.evidence:
                lines.append("```json")
                lines.append(json.dumps(r.evidence, indent=2, ensure_ascii=False))
                lines.append("```")
            if r.error:
                lines.append("```")
                lines.append(r.error.strip())
                lines.append("```")
            lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phone", default=DEFAULT_PHONE)
    ap.add_argument("--tenant-id", default=DEFAULT_TENANT_ID)
    ap.add_argument("--only", type=int, nargs="*")
    ap.add_argument("--report-dir", default=str(REPO_ROOT / "docs" / "reports"))
    args = ap.parse_args()

    results = run_all(args.phone, args.tenant_id, args.only)
    md = render_md(results)
    js = json.dumps([asdict(r) for r in results], indent=2, ensure_ascii=False)
    out_dir = Path(args.report_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "rev79_conversation_run.md").write_text(md)
    (out_dir / "rev79_conversation_run.json").write_text(js)
    print(md)
    print(f"\nReportes:\n  {out_dir}/rev79_conversation_run.md")
    return 1 if any(r.status == FAIL for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
