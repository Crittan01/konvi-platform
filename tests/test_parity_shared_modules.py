"""G11 — Paridad de módulos duplicados cross-servicio (guardarraíl anti-drift).

La unificación a paquete compartido está diferida (M16: rootDir por servicio en
Render lo impide sin cambio de deploy; decisión documentada en PLAN §B.2 G10).
Mientras tanto, el drift NO puede pasar en silencio: este test es el guard.

Cobertura:
  • Byte-paridad (idénticos, cambios se propagan juntos o revientan CI):
      llm_embed, carrier_capabilities.
      (Ya cubiertos aparte y NO repetidos aquí: aveonline_client —
       test_aveonline_client_parity; llm_cascade — test_llm_cascade_parity;
       phone — test_phone_helpers_pact.)
  • Paridad FUNCIONAL por AST (mismo comportamiento; comentarios/docstrings
      pueden divergir legítimamente):
      - vault_helper ×3 (api / orchestrator / connector) — todas las funciones.
      - wompi_client: las 3 funciones del orchestrator (void + eligibility +
        creds) ⊆ cliente canónico del api con AST idéntico por función.
        (El comentario del módulo citaba un inexistente test_wompi_void.py —
        ESTE es el guard real.)
      (observability.py ×3 tenía guard aquí — eliminado en S8 junto con los
      módulos; el OTEL del orchestrator vive ahora en tracing.py, sin espejo.)
"""
import ast
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
API = REPO_ROOT / "services" / "api"
ORCH = REPO_ROOT / "services" / "ai-orchestrator"
CONN = REPO_ROOT / "services" / "connector-whatsapp"


def _ast_sin_docs(path: Path) -> dict[str, str]:
    """nombre → ast.dump de la función/constante sin docstrings ni comentarios."""
    tree = ast.parse(path.read_text())
    out: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for child in ast.walk(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
                    body = getattr(child, "body", None)
                    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
                        child.body = body[1:]
            out[node.name] = ast.dump(node)
    return out


class ByteParityTests(unittest.TestCase):
    """Módulos byte-idénticos entre servicios (sin guard previo)."""

    def test_llm_embed_identico(self):
        a = (API / "lib" / "llm_embed.py").read_bytes()
        b = (ORCH / "llm_embed.py").read_bytes()
        self.assertEqual(a, b, "llm_embed.py divergió api↔orchestrator — propagar el cambio a ambos")

    def test_carrier_capabilities_identico(self):
        a = (API / "lib" / "carrier_capabilities.py").read_bytes()
        b = (ORCH / "lib" / "carrier_capabilities.py").read_bytes()
        self.assertEqual(a, b, "carrier_capabilities.py divergió api↔orchestrator")


class VaultHelperParityTests(unittest.TestCase):
    """Las 3 copias de vault_helper deben tener el mismo comportamiento
    (los comentarios difieren de forma legítima — documentan el origen)."""

    def test_funciones_identicas_en_las_3_copias(self):
        a = _ast_sin_docs(API / "vault_helper.py")
        o = _ast_sin_docs(ORCH / "vault_helper.py")
        c = _ast_sin_docs(CONN / "lib" / "vault_helper.py")
        self.assertEqual(set(a), set(o), "api↔orchestrator: conjunto de funciones difiere")
        self.assertEqual(set(a), set(c), "api↔connector: conjunto de funciones difiere")
        for name in a:
            self.assertEqual(a[name], o[name], f"vault_helper.{name} divergió api↔orchestrator")
            self.assertEqual(a[name], c[name], f"vault_helper.{name} divergió api↔connector")


class WompiClientParityTests(unittest.TestCase):
    """La copia reducida del orchestrator (void + eligibility + creds) debe ser
    AST-idéntica a las funciones homónimas del cliente canónico del api."""

    ORCH_FUNCS = ("void_transaction_sync", "is_void_eligible", "get_tenant_wompi_creds")

    def test_wrappers_orchestrator_subset_exacto_del_api(self):
        a = _ast_sin_docs(API / "integrations" / "wompi_client.py")
        o = _ast_sin_docs(ORCH / "integrations" / "wompi_client.py")
        for name in self.ORCH_FUNCS:
            self.assertIn(name, o, f"falta {name} en la copia del orchestrator")
            self.assertIn(name, a, f"falta {name} en el canónico del api")
            self.assertEqual(
                a[name], o[name],
                f"wompi_client.{name} divergió (orchestrator ≠ api) — la copia "
                f"reducida debe propagar los cambios del canónico",
            )


if __name__ == "__main__":
    unittest.main()
