"""Test F.10 — worker invoca fn_cleanup_webhook_secrets RPC en maintenance loop.

Cobertura:
  1. Happy path: la RPC 'fn_cleanup_webhook_secrets' aparece entre las llamadas
     a supabase.rpc durante _run_idempotency_cleanup_if_due.
  2. Fallback: si la RPC no existe (migration no aplicada), worker NO crashea
     — el except Exception: pass del patrón canónico tolera.
"""
from __future__ import annotations

import asyncio
import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[1]
ORCH_ROOT = REPO_ROOT / "services" / "ai-orchestrator"


def _load_worker_module():
    """Carga worker.py con stubs mínimos para evitar conectar a Supabase real."""
    # Stub supabase + dependencies que worker.py importa al top-level.
    if str(ORCH_ROOT) not in sys.path:
        sys.path.insert(0, str(ORCH_ROOT))

    # worker.py importa muchas cosas que requieren env vars. Cargamos con
    # importlib raw después de stubear lo crítico.
    if "worker" in sys.modules:
        return sys.modules["worker"]
    spec = importlib.util.spec_from_file_location(
        "worker", ORCH_ROOT / "worker.py",
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["worker"] = mod
    spec.loader.exec_module(mod)
    return mod


# ─── Fake Supabase client mínimo ──────────────────────────────────────────────


class _FakeRpcCall:
    """Mock de chained rpc().execute() de supabase-py."""

    def __init__(self, fn_name: str, args, registry, fail_for: set[str]):
        self._fn_name = fn_name
        self._args = args
        self._registry = registry
        self._fail_for = fail_for

    def execute(self):
        self._registry.append({"fn": self._fn_name, "args": self._args})
        if self._fn_name in self._fail_for:
            # Simular "function does not exist" como Postgrest lo lanzaría.
            raise Exception(
                f"{{\"code\":\"PGRST202\",\"message\":\"function {self._fn_name} does not exist\"}}"
            )
        return SimpleNamespace(data=[0])


class _FakeSupabase:
    def __init__(self, fail_for: set[str] | None = None):
        self.rpc_calls: list[dict] = []
        self._fail_for = fail_for or set()

    def rpc(self, fn_name: str, args=None):
        return _FakeRpcCall(fn_name, args, self.rpc_calls, self._fail_for)


# ─── Tests ────────────────────────────────────────────────────────────────────


class WorkerWebhookSecretsCleanupTests(unittest.TestCase):
    """Verifica wiring F.10 del worker."""

    @classmethod
    def setUpClass(cls):
        # Cargar el módulo una sola vez (es pesado por imports transitivos).
        cls.worker_mod = _load_worker_module()

    def _build_worker_with_fake_supabase(self, fail_for=None):
        """Construye instancia Worker con supabase mock + bypass de __init__
        pesado (no necesitamos pgmq real, queue real, etc.)."""
        WorkerCls = self.worker_mod.OrchestratorWorker
        # Bypass __init__ — solo seteamos lo que _run_idempotency_cleanup_if_due
        # necesita.
        instance = WorkerCls.__new__(WorkerCls)
        instance.supabase = _FakeSupabase(fail_for=fail_for)
        instance._cleanup_enabled = True
        instance._last_cleanup_at = None  # nunca ejecutado → arranca ya
        instance._metrics = {
            "idempotency_cleanup_runs": 0,
            "idempotency_cleanup_deleted": 0,
            "last_cleanup_deleted": 0,
        }
        return instance

    def test_worker_invoca_fn_cleanup_webhook_secrets(self):
        """Happy path: cleanup loop incluye fn_cleanup_webhook_secrets en RPCs."""
        async def go():
            w = self._build_worker_with_fake_supabase()
            await w._run_idempotency_cleanup_if_due()
            fn_names = [c["fn"] for c in w.supabase.rpc_calls]
            self.assertIn(
                "fn_cleanup_webhook_secrets",
                fn_names,
                f"Esperaba 'fn_cleanup_webhook_secrets' en RPC calls, vi: {fn_names}",
            )
        asyncio.run(go())

    def test_worker_tolera_funcion_inexistente(self):
        """Fallback: si la migration 20260614110000 no está aplicada, worker
        NO debe crashear. El except Exception: pass del patrón canónico aplica."""
        async def go():
            w = self._build_worker_with_fake_supabase(
                fail_for={"fn_cleanup_webhook_secrets"},
            )
            # Si crashea, este await levanta. Si tolera, sigue.
            await w._run_idempotency_cleanup_if_due()
            # La RPC se intentó.
            fn_names = [c["fn"] for c in w.supabase.rpc_calls]
            self.assertIn("fn_cleanup_webhook_secrets", fn_names)
        asyncio.run(go())

    def test_orden_de_cleanups_canonico(self):
        """fn_cleanup_webhook_secrets debe ejecutarse DESPUÉS de meli_webhook_dedup
        (siguiente bloque inmediato en el flow del worker). Asegura que no se
        ejecuta antes de tiempo / no rompe el orden de los RPCs existentes."""
        async def go():
            w = self._build_worker_with_fake_supabase()
            await w._run_idempotency_cleanup_if_due()
            fn_names = [c["fn"] for c in w.supabase.rpc_calls]
            meli_idx = fn_names.index("cleanup_expired_meli_webhook_dedup")
            secrets_idx = fn_names.index("fn_cleanup_webhook_secrets")
            self.assertGreater(
                secrets_idx, meli_idx,
                "fn_cleanup_webhook_secrets debe ir DESPUÉS de "
                "cleanup_expired_meli_webhook_dedup en el flow",
            )
        asyncio.run(go())


if __name__ == "__main__":
    unittest.main()
