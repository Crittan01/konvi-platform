"""FITNESS FUNCTION (A11, Clase A — firma desincronizada) —
_mark_message_processing siempre recibe tenant_id + message_id.

El bug que rompía CADA turno agentic (degraded mode + doble-respuesta) fue 14
call-sites en dispatcher.py con la firma vieja `(supabase, message_id, ...)` —
faltaba tenant_id como 2º posicional tras el refactor A6.2.7. Los tests pasaban
porque mockeaban supabase. Firma canónica:
    _mark_message_processing(supabase, tenant_id, message_id, processing_status=...)

Este AST-check falla si CUALQUIER call-site (dispatcher u orchestrator) deja de
pasar tenant_id Y message_id. Corre SIEMPRE en la suite (anti-no-op durable).
"""
import ast
import os
import unittest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
TARGETS = [
    os.path.join(REPO, "services", "ai-orchestrator", "agentic", "dispatcher.py"),
    os.path.join(REPO, "services", "ai-orchestrator", "orchestrator.py"),
]
FN = "_mark_message_processing"


def _call_provides_tenant_and_message(node: ast.Call) -> bool:
    """Firma canónica: (supabase, tenant_id, message_id, ...). Un call es válido
    si tenant_id (2º) y message_id (3º) llegan — por posición o por keyword.

    Catalogamos como ROTO la forma exacta del bug: 2 posicionales
    (supabase, message_id) sin tenant_id/message_id como keyword.
    """
    n_pos = len(node.args)
    kw = {k.arg for k in node.keywords if k.arg}
    if n_pos >= 3:
        return True  # supabase, tenant_id, message_id posicionales
    if n_pos >= 2 and "message_id" in kw:
        return True  # supabase, tenant_id posicionales + message_id kw
    if "tenant_id" in kw and "message_id" in kw:
        return True  # ambos por keyword
    return False


def _bad_call_sites():
    bad = []
    for path in TARGETS:
        tree = ast.parse(open(path, encoding="utf-8").read())
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == FN):
                if not _call_provides_tenant_and_message(node):
                    bad.append(f"{os.path.relpath(path, REPO)}:{node.lineno}")
    return bad


class MarkMessageProcessingSignatureTests(unittest.TestCase):
    def test_all_call_sites_pass_tenant_and_message(self):
        bad = _bad_call_sites()
        self.assertEqual(
            bad, [],
            f"call-sites de {FN} con firma vieja (sin tenant_id) — reintroducen el "
            f"bug de degraded-mode cada turno: {bad}",
        )

    def test_guard_detects_the_broken_form(self):
        # Auto-validación (fixture-bug): la forma exacta del bug original DEBE
        # ser detectada como rota por el predicado.
        broken = ast.parse("_mark_message_processing(supabase, message_id, processing_status=X)").body[0].value
        self.assertFalse(_call_provides_tenant_and_message(broken))
        # Y la forma canónica DEBE pasar.
        good = ast.parse("_mark_message_processing(supabase, tenant_id, message_id, processing_status=X)").body[0].value
        self.assertTrue(_call_provides_tenant_and_message(good))


if __name__ == "__main__":
    unittest.main()
