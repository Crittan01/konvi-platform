"""Rev. 103 — Tests del cap de consent_evidence.renewals_after_revocation.

JSONB soporta MB pero un cap preventivo a 50 entries:
  • Mejora performance de SAR exports (no se cargan arrays gigantes).
  • Marker `renewals_truncated_at` documenta el truncamiento ante SIC.
  • La integridad legal se mantiene: las últimas 50 son las relevantes
    operacionalmente; el audit_log inmutable conserva el historial completo.
"""
from pathlib import Path
import unittest

REPO = Path('/home/ansible/workspaces/commerce-ops-platform')
PAGE_TSX = REPO / 'apps/web/app/dashboard/(sales)/contacts/page.tsx'


class ConsentEvidenceCapTests(unittest.TestCase):
    """editContact aplica cap a renewals_after_revocation."""

    def setUp(self):
        self.page_src = PAGE_TSX.read_text()

    def test_caps_renewals_to_last_50(self):
        # arr.length > 50 → arr.slice(-50)
        self.assertIn(
            'arr.slice(-50)',
            self.page_src,
        )

    def test_truncation_marker_present(self):
        # Cuando se cap'ea, queda marker `renewals_truncated_at`.
        self.assertIn(
            "mergedEvidence.renewals_truncated_at = nowIso",
            self.page_src,
        )

    def test_truncation_count_persisted(self):
        # Cuántas entries se truncaron — útil para audit ante SIC.
        self.assertIn(
            'mergedEvidence.renewals_truncated_count = arr.length - 50',
            self.page_src,
        )

    def test_cap_only_runs_when_array(self):
        # Guarda contra null/object — solo aplica cuando es array.
        self.assertIn(
            'Array.isArray(mergedEvidence.renewals_after_revocation)',
            self.page_src,
        )


if __name__ == '__main__':
    unittest.main()
