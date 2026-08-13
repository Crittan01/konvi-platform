"""A9 finiquito — máquina de estados de consent movida al API PATCH.

editContact (server action UI) tenía una máquina de estados de consent (Habeas
Data Ley 1581) que difería de la lógica del API PATCH → migrarlo a ciegas
cambiaría la semántica legal. Decisión founder: mover la lógica API-side
(_compute_consent_update) con tests que verifiquen el comportamiento, luego
editContact solo hace fetch PATCH.

Estos tests verifican que _compute_consent_update replica editContact:
guards (soft-revoke, renovación), mergedEvidence + renewals_after_revocation,
effectiveConsentGiven, consent_date/revoked transitions, attachment.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))

from fastapi import HTTPException  # noqa: E402
from routers.contacts import _compute_consent_update, ContactPatch  # noqa: E402

NOW = "2026-06-24T12:00:00+00:00"


def _compute(patch_kwargs, current, *, incoming_pii=True, actor="op@kaiu.co"):
    return _compute_consent_update(
        patch=ContactPatch(**patch_kwargs),
        current=current,
        incoming_pii=incoming_pii,
        actor_email=actor,
        now_iso=NOW,
    )


class InitialConsentTests(unittest.TestCase):
    def test_initial_consent_sets_date_and_evidence(self):
        # prev sin consent → consent_given=true: consent_date=now, last_update.
        out = _compute(
            {"consent_given": True, "consent_source": "manual_console"},
            {"consent_given": False, "consent_date": None, "consent_evidence": {}},
        )
        self.assertTrue(out["consent_given"])
        self.assertEqual(out["consent_date"], NOW)
        self.assertEqual(out["consent_channel"], "dashboard_console")
        self.assertEqual(out["consent_evidence"]["last_update"]["actor_email"], "op@kaiu.co")
        self.assertIsNone(out["consent_revoked_at"])

    def test_reconsent_preserves_original_date(self):
        # prev YA con consent → re-guardar mantiene consent_date original.
        out = _compute(
            {"consent_given": True, "consent_source": "manual_console"},
            {"consent_given": True, "consent_date": "2026-01-01T00:00:00+00:00",
             "consent_evidence": {"foo": "bar"}},
        )
        self.assertEqual(out["consent_date"], "2026-01-01T00:00:00+00:00")
        self.assertIsNone(out["consent_revoked_at"])
        # Preserva evidence previa + agrega last_update.
        self.assertEqual(out["consent_evidence"]["foo"], "bar")
        self.assertIn("last_update", out["consent_evidence"])


class SoftRevokeGuardTests(unittest.TestCase):
    def test_soft_revoke_blocked(self):
        # prev consent_given=true + consent_given=false sin renovación → 422.
        with self.assertRaises(HTTPException) as ctx:
            _compute(
                {"consent_given": False},
                {"consent_given": True, "consent_date": "2026-01-01", "consent_evidence": {}},
            )
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertIn("Anonimizar", ctx.exception.detail)

    def test_revoke_ok_if_already_no_consent(self):
        # prev sin consent + consent_given=false → no es soft-revoke (no levanta).
        out = _compute(
            {"consent_given": False},
            {"consent_given": False, "consent_date": None, "consent_evidence": {}},
            incoming_pii=False,
        )
        self.assertFalse(out["consent_given"])


class RenewalAfterAnonymizationTests(unittest.TestCase):
    ANON = {
        "consent_given": False,
        "consent_revoked_at": "2026-02-01T00:00:00+00:00",
        "consent_date": None,
        "consent_evidence": {"prev": 1},
    }

    def test_renewal_reactivates_and_logs(self):
        out = _compute(
            {"consent_given": True, "consent_source": "in_person",
             "renewed_consent": True, "renewed_consent_evidence": "Cliente firmó en tienda hoy"},
            self.ANON,
        )
        self.assertTrue(out["consent_given"])
        self.assertEqual(out["consent_date"], NOW)  # renovación = fecha fresca
        renewals = out["consent_evidence"]["renewals_after_revocation"]
        self.assertEqual(len(renewals), 1)
        self.assertEqual(renewals[0]["previous_revoked_at"], "2026-02-01T00:00:00+00:00")
        self.assertEqual(renewals[0]["evidence_text"], "Cliente firmó en tienda hoy")

    def test_renewal_requires_flag_when_pii_incoming(self):
        with self.assertRaises(HTTPException) as ctx:
            _compute(
                {"consent_given": True, "consent_source": "in_person"},  # sin renewed_consent
                self.ANON, incoming_pii=True,
            )
        self.assertEqual(ctx.exception.status_code, 422)

    def test_renewal_requires_evidence_min_length(self):
        with self.assertRaises(HTTPException):
            _compute(
                {"consent_given": True, "consent_source": "in_person",
                 "renewed_consent": True, "renewed_consent_evidence": "corto"},  # <10
                self.ANON, incoming_pii=True,
            )

    def test_renewals_capped_at_50(self):
        prev_renewals = [{"at": f"r{i}"} for i in range(50)]
        anon = dict(self.ANON, consent_evidence={"renewals_after_revocation": prev_renewals})
        out = _compute(
            {"consent_given": True, "consent_source": "in_person",
             "renewed_consent": True, "renewed_consent_evidence": "evidencia renovada válida"},
            anon,
        )
        renewals = out["consent_evidence"]["renewals_after_revocation"]
        self.assertEqual(len(renewals), 50)  # capped
        self.assertEqual(out["consent_evidence"]["renewals_truncated_count"], 1)


class AttachmentTests(unittest.TestCase):
    def test_attachment_metadata_merged(self):
        out = _compute(
            {"consent_given": True, "consent_source": "in_person",
             "consent_attachment": {"attachment_path": "ev/abc.jpg", "attachment_mime": "image/jpeg"}},
            {"consent_given": False, "consent_date": None,
             "consent_evidence": {"attachment_url": "legacy://x"}},
        )
        ev = out["consent_evidence"]
        self.assertEqual(ev["attachment_path"], "ev/abc.jpg")
        self.assertNotIn("attachment_url", ev)  # legacy limpiado


if __name__ == "__main__":
    unittest.main()
