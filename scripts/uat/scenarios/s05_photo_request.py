#!/usr/bin/env python3.11
"""S5 — Petición de foto del producto (multi-path).

OBJETIVO: validar los 2 paths del image_send_tool:

  • S5.a (sin foto): "¿Tienes foto del jabón de coco?"
       Ningún variant ni cover tiene image_url → bot da fallback
       explicativo con descripción + presentaciones disponibles.
       Critical: NO debe inventar URL de imagen, NO debe quedarse mudo.

  • S5.b (con foto): "¿Tienes foto del Aceite de Argán?"
       Producto tiene cover_image_url → bot envía content_type=image
       con caption (título + variante + precio + descripción + CTA).
       Validamos: outbound con content_type=image presente.

PASS: ambos sub-escenarios pasan.
"""
from __future__ import annotations
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.harness import (  # noqa: E402
    PASS, FAIL, ScenarioResult, ConversationDriver, Rule,
    hard_reset, now_iso, run_one,
    seed_known_contact,
)
import e2e_chat  # noqa: E402

SUPPORTED_MODES = ("new", "known")


def _run_subtest(
    phone: str, tenant_id: str, label: str, opening: str, expect_image: bool,
) -> tuple[str, str, str, dict]:
    """Ejecuta un sub-test fotográfico aislado.

    Retorna (label, status, reason, evidence).
    """
    hard_reset(phone, tenant_id)

    if mode == "known":

        sb_seed = e2e_chat._supabase()

        if not seed_known_contact(sb_seed, tenant_id, phone, name="Cristian"):

            return ScenarioResult(0, scenario.__name__, FAIL, "Seed known contact falló")
    time.sleep(2)
    photo_rules: list[Rule] = [
        (40, ("cuál producto", "cual producto", "cuéntame su nombre",
              "qué producto", "de cuál", "de cual"),
            lambda _: "Del jabón artesanal de coco" if "jabón" in opening.lower() else "Del Aceite de Argán"),
        (35, ("presentación", "presentacion", "gramaje", "60g", "100g",
              "volumen", "ml", "30ml", "60ml"),
            lambda _: "La de 30 ml"),
    ]
    drv = ConversationDriver(phone, tenant_id, photo_rules, max_turns=4)
    t0 = now_iso()
    res = drv.run(opening)

    sb = e2e_chat._supabase()
    conv = e2e_chat._find_conversation(sb, tenant_id, phone)
    if not conv:
        return label, FAIL, "Sin conversación creada", {"turns": res.turns}
    msgs = e2e_chat._last_messages(sb, conv["id"], limit=20)
    outs = [m for m in msgs if m.get("direction") == "outbound"
            and (m.get("created_at") or "") > t0]
    has_image = any(o.get("content_type") == "image" for o in outs)
    text = " ".join(o.get("content") or "" for o in outs).lower()

    evidence = {
        "turns": res.turns,
        "image_sent": has_image,
        "outbound_count": len(outs),
        "preview": text[:240],
    }

    if expect_image:
        # Path A — debe haber sido enviada al menos UNA imagen.
        if has_image:
            return label, PASS, "Bot envió imagen real (path A)", evidence
        return label, FAIL, "Esperaba imagen pero solo hubo texto", evidence
    else:
        # Path B — fallback explicativo: sin imagen, con tokens de
        # respuesta honesta.
        has_fallback = any(k in text for k in (
            "no tengo", "no dispongo", "imagen disponible",
            "no dispongo de", "aún no tengo foto", "aun no tengo foto",
            "cargada en el catálogo", "cargada en el catalogo",
        ))
        if has_image:
            return label, FAIL, "Esperaba fallback pero envió imagen", evidence
        if has_fallback:
            return label, PASS, "Bot dio fallback explicativo (path B)", evidence
        return label, FAIL, "Bot ni imagen ni fallback explicativo", evidence


def scenario(phone: str, tenant_id: str, mode: str = "new") -> ScenarioResult:
    sub_tests = [
        ("sin_foto",  "¿Tienes foto del jabón de coco?",      False),
        ("con_foto",  "¿Tienes foto del Aceite de Argán?",    True),
    ]
    results: list[tuple[str, str, str, dict]] = []
    for label, msg, expect_image in sub_tests:
        results.append(_run_subtest(phone, tenant_id, label, msg, expect_image))

    passes = sum(1 for _, st, _, _ in results if st == PASS)
    total = len(results)

    if passes == total:
        return ScenarioResult(5, "Foto producto (multi-path)", PASS,
            f"Todos los {total} sub-escenarios pasaron",
            evidence={"sub_results": [
                {"label": l, "status": s, "reason": r, "evidence": e}
                for l, s, r, e in results
            ]})

    fails_summary = "; ".join(
        f"{l}={s}({r})" for l, s, r, _ in results if s != PASS
    )
    return ScenarioResult(5, "Foto producto (multi-path)", FAIL,
        f"{passes}/{total} sub-escenarios pasaron — fallos: {fails_summary}",
        evidence={"sub_results": [
            {"label": l, "status": s, "reason": r, "evidence": e}
            for l, s, r, e in results
        ]})


if __name__ == "__main__":
    sys.exit(run_one(scenario))
