"""Auditoría estática: el código no debe contener strings robóticas que lleguen al cliente.

Escanea archivos Python en services/ai-orchestrator/ y services/api/routers/ y
busca patrones robóticos prohibidos. Si los detecta dentro de literales que se
envían al cliente, falla el test.

Falsos positivos: el catálogo de patrones es conservador. Si un patrón legítimo
necesita aparecer (ej. mensaje legal), agregar al ALLOWLIST con justificación.
"""
import os
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Frases robóticas prohibidas en respuestas al cliente.
# Mantener conservador: solo frases que claramente suenan a script automatizado.
_FORBIDDEN_PATTERNS = [
    r"Procesando su solicitud",
    r"Estamos procesando su",
    r"Lamentamos los inconvenientes ocasionados",
    r"Su solicitud ha sido recibida y será atendida",
    r"Estimado cliente,?\s",  # impersonal y robótico
]

# Archivos a auditar. Solo donde se generan mensajes que el cliente recibe.
_SCAN_DIRS = [
    REPO_ROOT / "services" / "ai-orchestrator",
    REPO_ROOT / "services" / "api" / "routers",
]

# Excepciones explícitas: paths o frases que pueden contener un patrón sin ser
# texto al cliente (ej. instrucciones AL LLM dentro del system prompt — donde
# le DECIMOS al LLM que NO use esa frase).
_ALLOWLIST: dict[str, str] = {
    # archivo : justificación
    "services/ai-orchestrator/orchestrator.py": (
        "El system prompt y la guía humana incluyen las frases prohibidas "
        "como NEGATIVAS (\"NUNCA uses Procesando su solicitud\") — eso es "
        "intencional y no llega al cliente."
    ),
}


def _python_files(roots: list[Path]) -> list[Path]:
    out: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for p in root.rglob("*.py"):
            if "__pycache__" in p.parts or "tests" in p.parts:
                continue
            out.append(p)
    return out


class HumanizationAuditTests(unittest.TestCase):
    def test_no_forbidden_phrases_in_client_facing_code(self):
        offenders: list[str] = []
        for path in _python_files(_SCAN_DIRS):
            rel = str(path.relative_to(REPO_ROOT))
            try:
                src = path.read_text(encoding="utf-8")
            except OSError:
                continue
            for pat in _FORBIDDEN_PATTERNS:
                for m in re.finditer(pat, src):
                    line_no = src.count("\n", 0, m.start()) + 1
                    snippet = src.splitlines()[line_no - 1].strip()[:120]
                    if rel in _ALLOWLIST:
                        # archivo permitido (frase aparece como NEGATIVA en system prompt)
                        continue
                    offenders.append(f"{rel}:{line_no}: '{pat}' en `{snippet}`")
        if offenders:
            msg = "Frases robóticas detectadas en código que llega al cliente:\n  " + "\n  ".join(offenders)
            self.fail(msg)

    def test_safety_greeting_bank_has_no_robotic_phrases(self):
        # Importa el banco y verifica directamente.
        import sys
        sys.path.insert(0, str(REPO_ROOT / "services" / "ai-orchestrator"))
        os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
        os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")
        os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")
        os.environ.setdefault("GEMINI_API_KEY", "test")
        from orchestrator import _SAFETY_GREETING_BANK

        for tono, variants in _SAFETY_GREETING_BANK.items():
            for v in variants:
                for pat in _FORBIDDEN_PATTERNS:
                    self.assertFalse(
                        re.search(pat, v),
                        f"variante '{tono}' contiene patrón prohibido {pat!r}: {v!r}",
                    )

    def test_templated_variant_constants_have_no_robotic_phrases(self):
        # Verifica los buckets de variantes determinísticas adicionales.
        import sys
        sys.path.insert(0, str(REPO_ROOT / "services" / "ai-orchestrator"))
        os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
        from orchestrator import (
            _CANCEL_SUCCESS_VARIANTS,
            _CANCEL_NONE_VARIANTS,
            _REACTIVATION_VARIANTS,
            _CORRECTION_PROMPT_VARIANTS,
        )

        all_strings: list[str] = []
        all_strings.extend(_CANCEL_SUCCESS_VARIANTS)
        all_strings.extend(_CANCEL_NONE_VARIANTS)
        all_strings.extend(_REACTIVATION_VARIANTS)
        for variants in _CORRECTION_PROMPT_VARIANTS.values():
            all_strings.extend(variants)

        for s in all_strings:
            for pat in _FORBIDDEN_PATTERNS:
                self.assertFalse(re.search(pat, s), f"variante con patrón prohibido: {s!r}")


if __name__ == "__main__":
    unittest.main()
