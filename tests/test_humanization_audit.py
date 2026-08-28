"""Auditoría estática: el código no debe contener strings robóticas que lleguen al cliente.

Escanea archivos Python en services/ai-orchestrator/ y services/api/routers/ y
busca patrones robóticos prohibidos. Si los detecta dentro de literales que se
envían al cliente, falla el test.

Falsos positivos: el catálogo de patrones es conservador. Si un patrón legítimo
necesita aparecer (ej. mensaje legal), agregar al ALLOWLIST con justificación.
"""
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
# B-2 Fase 0 (2026-08-28): la allowlist quedó VACÍA — `orchestrator.py` ya no
# contiene las frases (la guía de estilo muerta `_HUMAN_STYLE_GUIDE` fue
# retirada con las 10 constantes de política del path V1 extinto).
_ALLOWLIST: dict[str, str] = {}


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


if __name__ == "__main__":
    unittest.main()
