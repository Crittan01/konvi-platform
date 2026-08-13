"""Rev. 103 — Tests del cap de consent_evidence.renewals_after_revocation.

JSONB soporta MB pero un cap preventivo a 50 entries:
  • Mejora performance de SAR exports (no se cargan arrays gigantes).
  • Marker `renewals_truncated_at` documenta el truncamiento ante SIC.
  • La integridad legal se mantiene: las últimas 50 son las relevantes
    operacionalmente; el audit_log inmutable conserva el historial completo.
"""
from pathlib import Path
import unittest

REPO = Path(__file__).resolve().parents[1]
# A9 finiquito — el cap de renewals_after_revocation MIGRÓ del server action
# page.tsx al API router contacts.py (_compute_consent_update). Comportamiento
# verificado byte-a-byte en tests/test_a9_editcontact_consent.py.
CONTACTS_API_PY = REPO / 'services/api/routers/contacts.py'


class ConsentEvidenceCapTests(unittest.TestCase):
    """El cap a renewals_after_revocation ahora vive en el API router."""

    def setUp(self):
        self.api_src = CONTACTS_API_PY.read_text()

    def test_caps_renewals_to_last_50(self):
        self.assertIn('_MAX_RENEWALS = 50', self.api_src)
        self.assertIn('prev_renewals[-_MAX_RENEWALS:]', self.api_src)

    def test_truncation_marker_present(self):
        self.assertIn('"renewals_truncated_at"', self.api_src)

    def test_truncation_count_persisted(self):
        self.assertIn('"renewals_truncated_count"', self.api_src)

    def test_cap_only_runs_when_array(self):
        # Guarda contra null/object — solo aplica cuando es lista.
        self.assertIn('isinstance(prev_renewals, list)', self.api_src)


if __name__ == '__main__':
    unittest.main()
