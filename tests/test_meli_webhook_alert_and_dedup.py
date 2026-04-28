"""Tests para alerta proactiva rejected_origin (B3) e idempotencia distribuida (C2) — rev. 69.

Cubre:
- _check_meli_origin_alert: contador in-memory + threshold + log warning.
- _is_duplicate_event con RPC distribuida (mock supabase) + fallback in-memory.
"""
import importlib
import os
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")

sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/api")


def _reload_module(env: dict | None = None):
    for k, v in (env or {}).items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    from routers import meli_webhook as mw
    return importlib.reload(mw)


class MeliOriginAlertTests(unittest.TestCase):
    def setUp(self):
        self.mw = _reload_module({
            "MELI_WEBHOOK_ALERT_THRESHOLD": "5",
            "MELI_WEBHOOK_ALERT_WINDOW_SECONDS": "300",
            "MELI_WEBHOOK_ALLOWED_IPS": "",
        })
        self.mw._alert_counters.clear()

    def test_below_threshold_no_warning(self):
        with patch.object(self.mw.logger, "warning") as warn:
            for _ in range(3):  # 3 < threshold 5
                self.mw._check_meli_origin_alert("9.9.9.9")
            warn.assert_not_called()

    def test_at_threshold_emits_alert(self):
        with patch.object(self.mw.logger, "warning") as warn:
            for _ in range(5):
                self.mw._check_meli_origin_alert("9.9.9.9")
            self.assertTrue(warn.called)
            # Verifica que el log incluye el formato esperado
            call_args = warn.call_args[0][0]
            self.assertIn("alert_threshold_exceeded", call_args)

    def test_different_ips_count_separately(self):
        with patch.object(self.mw.logger, "warning") as warn:
            for ip in ["1.1.1.1", "2.2.2.2", "3.3.3.3", "4.4.4.4", "5.5.5.5"]:
                self.mw._check_meli_origin_alert(ip)
            # 5 IPs distintas, cada una 1 vez: ningún contador alcanza 5.
            warn.assert_not_called()

    def test_old_timestamps_cleaned_outside_window(self):
        # Simular rechazos ANTIGUOS (>300s atrás) que NO deben contar.
        old_ts = time.time() - 600
        self.mw._alert_counters["7.7.7.7"] = [old_ts] * 4  # 4 antiguos
        with patch.object(self.mw.logger, "warning") as warn:
            self.mw._check_meli_origin_alert("7.7.7.7")  # 1 nuevo
            warn.assert_not_called()  # Solo 1 dentro de ventana

    def test_empty_ip_no_op(self):
        with patch.object(self.mw.logger, "warning") as warn:
            self.mw._check_meli_origin_alert("")
            warn.assert_not_called()


class MeliDedupRpcTests(unittest.TestCase):
    def setUp(self):
        self.mw = _reload_module({"MELI_WEBHOOK_ALLOWED_IPS": ""})
        self.mw._dedup_seen.clear()

    def test_rpc_returns_false_event_not_duplicate(self):
        sb = MagicMock()
        sb.rpc.return_value.execute.return_value = MagicMock(data=False)
        result = self.mw._is_duplicate_event("app1", "/orders/1", "2026-04-30T10:00:00Z", sb)
        self.assertFalse(result)
        sb.rpc.assert_called_once()
        # Verifica los parámetros que se pasan a la RPC.
        rpc_args = sb.rpc.call_args
        self.assertEqual(rpc_args[0][0], "meli_webhook_seen")
        params = rpc_args[0][1]
        self.assertEqual(params["p_application_id"], "app1")
        self.assertEqual(params["p_resource"], "/orders/1")

    def test_rpc_returns_true_event_is_duplicate(self):
        sb = MagicMock()
        sb.rpc.return_value.execute.return_value = MagicMock(data=True)
        result = self.mw._is_duplicate_event("app1", "/orders/1", "2026-04-30T10:00:00Z", sb)
        self.assertTrue(result)

    def test_rpc_failure_falls_back_to_local(self):
        sb = MagicMock()
        sb.rpc.return_value.execute.side_effect = RuntimeError("RPC down")
        # Primera llamada — fallback in-memory devuelve False (evento nuevo)
        first = self.mw._is_duplicate_event("app2", "/orders/2", "ts", sb)
        self.assertFalse(first)
        # Segunda llamada con misma key — fallback in-memory devuelve True
        second = self.mw._is_duplicate_event("app2", "/orders/2", "ts", sb)
        self.assertTrue(second)

    def test_supabase_none_uses_local_dedup(self):
        # Backward compatibility: si supabase=None, usa el fallback in-memory.
        first = self.mw._is_duplicate_event("app3", "/orders/3", "ts", None)
        self.assertFalse(first)
        second = self.mw._is_duplicate_event("app3", "/orders/3", "ts", None)
        self.assertTrue(second)

    def test_empty_fields_never_dedup(self):
        sb = MagicMock()
        result = self.mw._is_duplicate_event("", "", "", sb)
        self.assertFalse(result)
        # No debe llamar al RPC con strings vacíos
        sb.rpc.assert_not_called()


if __name__ == "__main__":
    unittest.main()
