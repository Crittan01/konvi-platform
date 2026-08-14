"""G20 — router api insights (espejo server-side de /api/insights web).

Cubre: validación de shape de la respuesta de Gemini, prompts por módulo,
ventana Bogotá (espejo de lib/date-window), handler POST (happy path + 502s),
handler GET (feature-detect → insight null) y wiring del rate-limit
(bucket ai.insights, 10/h, tenant+user+IP). Sin Gemini ni Supabase reales:
_fetch_module_data / _generate_insight se mockean.
"""
import json
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
os.environ.setdefault("GEMINI_API_KEY", "test-key")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))

from fastapi import HTTPException  # noqa: E402

from routers.insights import (  # noqa: E402
    RL_AI_INSIGHTS,
    InsightRequest,
    _bogota_window_utc,
    _build_prompt,
    _validate_insight,
    generate_insight,
    get_last_insight,
    router as insights_router,
)

TENANT = "11111111-1111-1111-1111-111111111111"

VALID_LLM = {
    "resumen": "Vendiste $1.2M en 30d",
    "hallazgos": ["h1", "h2"],
    "acciones": [
        {"prioridad": "alta", "accion": "Confirmar pendientes"},
        {"prioridad": "media", "accion": "Reactivar clientes"},
        {"prioridad": "prioridad-invalida", "accion": "se filtra"},
        {"accion_sin_prioridad": True},
    ],
    "alerta": "  ",
}


def _request() -> MagicMock:
    return MagicMock(headers={"Authorization": "Bearer tok-user"})


def _call_post(module: str, llm_text: str | None):
    """Invoca el handler POST con data fetch + Gemini mockeados."""
    with (
        patch("routers.insights._fetch_module_data", return_value={"k": 1}),
        patch(
            "routers.insights._generate_insight",
            return_value=(
                (llm_text, 321, "gemini-3.1-flash-lite") if llm_text is not None
                else (None, None, None)
            ),
        ),
    ):
        return generate_insight(
            body=InsightRequest(module=module),
            request=_request(),
            tenant_id=TENANT,
            supabase=MagicMock(),
            _role="owner",
        )


class ValidateInsightTests(unittest.TestCase):
    def test_shape_valido_sanea_y_filtra(self):
        v = _validate_insight(VALID_LLM)
        self.assertIsNotNone(v)
        self.assertEqual(v["resumen"], VALID_LLM["resumen"])
        # acción con prioridad inválida y sin prioridad quedan fuera
        self.assertEqual([a["prioridad"] for a in v["acciones"]], ["alta", "media"])
        # alerta en blanco → None
        self.assertIsNone(v["alerta"])

    def test_caps_hallazgos_10_acciones_6(self):
        payload = {
            "resumen": "r",
            "hallazgos": [f"h{i}" for i in range(15)],
            "acciones": [{"prioridad": "baja", "accion": f"a{i}"} for i in range(9)],
        }
        v = _validate_insight(payload)
        self.assertEqual(len(v["hallazgos"]), 10)
        self.assertEqual(len(v["acciones"]), 6)

    def test_shapes_invalidos_dan_none(self):
        self.assertIsNone(_validate_insight(None))
        self.assertIsNone(_validate_insight("texto"))
        self.assertIsNone(_validate_insight({"resumen": "", "hallazgos": [], "acciones": []}))
        self.assertIsNone(_validate_insight({"resumen": "r", "hallazgos": "no-lista", "acciones": []}))
        self.assertIsNone(_validate_insight({"resumen": "r", "hallazgos": [1], "acciones": []}))
        self.assertIsNone(_validate_insight({"resumen": "r", "hallazgos": [], "acciones": "no-lista"}))


class PromptTests(unittest.TestCase):
    def test_prompt_orders_con_nota_de_dinero_canonica(self):
        p = _build_prompt("orders", {"recognized_revenue": 100})
        self.assertIn("DATOS DE PEDIDOS", p)
        self.assertIn("recognized_revenue", p)
        self.assertIn("nunca la llames ingreso", p)
        self.assertIn('"resumen"', p)  # json spec

    def test_prompt_metrics_menciona_periodo_previo(self):
        p = _build_prompt("metrics", {"messages_total": 5})
        self.assertIn("DATOS DE MÉTRICAS", p)
        self.assertIn("recognized_revenue_prev_30d", p)
        self.assertIn('"messages_total": 5', p)


class BogotaWindowTests(unittest.TestCase):
    def test_ventana_30d_empata_con_date_window_ts(self):
        # now = 2026-08-14T03:00Z = 2026-08-13 22:00 Bogotá → inicio 2026-07-15
        # 00:00 Bogotá = 2026-07-15T05:00Z (mismo caso verificado contra el TS).
        from_utc, to_utc = _bogota_window_utc(30, datetime(2026, 8, 14, 3, 0, 0, tzinfo=timezone.utc))
        self.assertTrue(from_utc.startswith("2026-07-15T05:00:00"))
        self.assertTrue(to_utc.startswith("2026-08-14T03:00:00"))


class GenerateInsightHandlerTests(unittest.TestCase):
    def test_modulo_invalido_400(self):
        with self.assertRaises(HTTPException) as ctx:
            _call_post("finanzas", json.dumps(VALID_LLM))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("Módulo no válido", ctx.exception.detail)

    def test_happy_path_limpia_fences_y_persiste(self):
        sb = MagicMock()
        with (
            patch("routers.insights._fetch_module_data", return_value={"k": 1}),
            patch(
                "routers.insights._generate_insight",
                return_value=(f"```json\n{json.dumps(VALID_LLM)}\n```", 321, "gemini-3.1-flash-lite"),
            ),
        ):
            r = generate_insight(
                body=InsightRequest(module="orders"),
                request=_request(),
                tenant_id=TENANT,
                supabase=sb,
                _role="owner",
            )
        self.assertEqual(r["resumen"], VALID_LLM["resumen"])
        self.assertEqual(len(r["acciones"]), 2)  # saneadas
        self.assertEqual(r["tokens_used"], 321)
        self.assertIn("generated_at", r)
        # best-effort: audit_log insert + upsert ai_insights
        tables = [c.args[0] for c in sb.table.call_args_list]
        self.assertIn("audit_log", tables)
        self.assertIn("ai_insights", tables)

    def test_cascade_degradado_502(self):
        with self.assertRaises(HTTPException) as ctx:
            _call_post("orders", None)
        self.assertEqual(ctx.exception.status_code, 502)
        self.assertIn("Error al consultar Gemini", ctx.exception.detail)

    def test_json_invalido_502(self):
        with self.assertRaises(HTTPException) as ctx:
            _call_post("orders", "esto no es JSON")
        self.assertEqual(ctx.exception.status_code, 502)
        self.assertIn("Respuesta inválida", ctx.exception.detail)

    def test_shape_inesperado_sin_acciones_502(self):
        bad = {"resumen": "r", "hallazgos": ["h"], "acciones": [], "alerta": None}
        with self.assertRaises(HTTPException) as ctx:
            _call_post("orders", json.dumps(bad))
        self.assertEqual(ctx.exception.status_code, 502)
        self.assertIn("formato inesperado", ctx.exception.detail)


class GetLastInsightTests(unittest.TestCase):
    def test_modulo_invalido_400(self):
        with self.assertRaises(HTTPException) as ctx:
            get_last_insight(module="nope", tenant_id=TENANT, supabase=MagicMock(), _role="owner")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_devuelve_insight_persistido(self):
        sb = MagicMock()
        (
            sb.table.return_value.select.return_value.eq.return_value.eq.return_value
            .maybe_single.return_value.execute.return_value
        ) = MagicMock(data={"result": VALID_LLM})
        r = get_last_insight(module="orders", tenant_id=TENANT, supabase=sb, _role="manager")
        self.assertEqual(r, {"insight": VALID_LLM})

    def test_sin_fila_o_error_feature_detect_da_null(self):
        sb_ok = MagicMock()
        (
            sb_ok.table.return_value.select.return_value.eq.return_value.eq.return_value
            .maybe_single.return_value.execute.return_value
        ) = MagicMock(data=None)
        self.assertEqual(
            get_last_insight(module="orders", tenant_id=TENANT, supabase=sb_ok, _role="owner"),
            {"insight": None},
        )
        sb_err = MagicMock()
        sb_err.table.side_effect = Exception("relation ai_insights does not exist")
        self.assertEqual(
            get_last_insight(module="orders", tenant_id=TENANT, supabase=sb_err, _role="owner"),
            {"insight": None},
        )


class RateLimitWiringTests(unittest.TestCase):
    """Wiring estructural — no golpea el limiter real (molde test_a11_catalog_ai)."""

    def test_rl_registrado_en_post_no_en_get(self):
        routes = {getattr(r, "path", ""): r for r in insights_router.routes}
        post = next(r for r in insights_router.routes if "POST" in getattr(r, "methods", set()))
        get = next(r for r in insights_router.routes if "GET" in getattr(r, "methods", set()))
        post_deps = [getattr(d, "dependency", None) for d in post.dependencies]
        get_deps = [getattr(d, "dependency", None) for d in get.dependencies]
        self.assertIn(RL_AI_INSIGHTS, post_deps)
        self.assertNotIn(RL_AI_INSIGHTS, get_deps)  # GET no gasta Gemini
        self.assertIn("/insights", routes)

    def test_bucket_y_tope_del_rule(self):
        closure = {
            var: cell.cell_contents
            for var, cell in zip(
                RL_AI_INSIGHTS.__code__.co_freevars,
                RL_AI_INSIGHTS.__closure__,
            )
        }
        rule = closure["rule"]
        self.assertEqual(rule.bucket, "ai.insights")
        self.assertEqual(rule.limit, 10)  # mismo tope que el insights web
        self.assertEqual(rule.window_seconds, 3600)
        self.assertTrue(closure["include_user_id"])


if __name__ == "__main__":
    unittest.main()
