"""Rev. 103 (SaaS B2B pivot) — Tests del MeLi import simple.

Filosofía:
  • El marketplace MeLi tiene su propia política; nosotros marcamos
    el origen con consent_source='marketplace_meli' y dejamos audit log.
  • El tenant es Responsable del tratamiento posterior (DPA cubre).
  • NO hay flags purpose_limited, NO hay restricciones especiales en
    orchestrator. El bot trata al contact como cualquier otro.

Cobertura:
  • _upsert_meli_contact crea contact con shape correcto.
  • Audit log se inserta con event='granted' source='system'.
  • Falla del audit NO aborta el upsert (warning + continúa).
  • Sin phone → return None (sin DB writes).
  • Migración añade marketplace_meli al CHECK constraint.
"""
import sys
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'services/api'))

# Stub minimal para el módulo `integrations.meli_client` (evita aiohttp deps).
sys.modules.setdefault('integrations', MagicMock())
sys.modules.setdefault('integrations.meli_client', MagicMock())

from routers.meli_webhook import _upsert_meli_contact, _hash_phone  # noqa: E402


class HashPhoneCoherenceTests(unittest.TestCase):
    """El _hash_phone local es espejo del orchestrator._hash_phone."""

    def test_same_hash_as_orchestrator_helper(self):
        # Importa el orchestrator helper para verificar coherencia.
        sys.path.insert(0, str(REPO / 'services/ai-orchestrator'))
        from orchestrator import _hash_phone as orch_hash
        for sample in ('+573125835649', '+57 312 583 5649', '57-312-583-5649'):
            self.assertEqual(_hash_phone(sample), orch_hash(sample))

    def test_returns_none_for_empty(self):
        self.assertIsNone(_hash_phone(None))
        self.assertIsNone(_hash_phone(''))


class UpsertMeliContactTests(unittest.TestCase):
    """_upsert_meli_contact crea contact + audit log."""

    def setUp(self):
        self.supabase = MagicMock()
        # Rev. 103 (D2) — El nuevo path hace SELECT legacy primero. Mock el
        # select chain para devolver `data=[]` (no hay legacy → usar upsert).
        select_chain = self.supabase.table.return_value.select.return_value
        select_chain.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
        self.upsert_chain = self.supabase.table.return_value.upsert
        self.upsert_chain.return_value.execute.return_value = MagicMock(
            data=[{'id': 'contact-uuid-123'}]
        )
        self.insert_chain = self.supabase.table.return_value.insert
        self.insert_chain.return_value.execute.return_value = MagicMock()

    def test_returns_none_without_phone(self):
        result = _upsert_meli_contact(
            buyer={'first_name': 'Juan'},
            tenant_id='t1',
            supabase=self.supabase,
            meli_order_id='ord-99',
        )
        self.assertIsNone(result)
        self.supabase.table.return_value.upsert.assert_not_called()

    def test_upserts_with_consent_source_marketplace_meli(self):
        result = _upsert_meli_contact(
            buyer={
                'first_name': 'Juan',
                'last_name': 'García',
                'phone': '3125835649',
            },
            tenant_id='t1',
            supabase=self.supabase,
            meli_order_id='2000003123456',
        )
        self.assertEqual(result, 'contact-uuid-123')

        # Tabla 'contacts' invocada con upsert.
        self.assertIn(
            'contacts',
            [c.args[0] for c in self.supabase.table.call_args_list],
        )
        upsert_payload = self.upsert_chain.call_args[0][0]
        self.assertEqual(upsert_payload['tenant_id'], 't1')
        # Rev. 104 (F0-4): phone canónico = digits-only, con prefix CO inferido
        # cuando es cel local de 10 dígitos. Ya NO usa formato E.164 con '+'.
        self.assertEqual(upsert_payload['phone'], '573125835649')
        self.assertEqual(upsert_payload['name'], 'Juan García')
        self.assertTrue(upsert_payload['consent_given'])
        self.assertEqual(upsert_payload['consent_source'], 'marketplace_meli')
        self.assertEqual(upsert_payload['consent_channel'], 'marketplace_meli')
        self.assertIn('consent_notice_version', upsert_payload)
        self.assertEqual(
            upsert_payload['consent_evidence']['meli_order_id'],
            '2000003123456',
        )
        self.assertEqual(
            upsert_payload['consent_evidence']['imported_from'],
            'mercadolibre',
        )

    def test_upsert_uses_on_conflict_tenant_phone(self):
        _upsert_meli_contact(
            buyer={'first_name': 'X', 'phone': '3001234567'},
            tenant_id='t1',
            supabase=self.supabase,
        )
        on_conflict = self.upsert_chain.call_args.kwargs.get('on_conflict')
        self.assertEqual(on_conflict, 'tenant_id,phone')

    def test_short_phone_returns_none(self):
        # Rev. 103 (D2): phone < 8 dígitos no normaliza → None.
        result = _upsert_meli_contact(
            buyer={'first_name': 'X', 'phone': '999'},
            tenant_id='t1',
            supabase=self.supabase,
        )
        self.assertIsNone(result)

    def test_inserts_audit_log_with_granted_event(self):
        _upsert_meli_contact(
            buyer={'first_name': 'X', 'phone': '3001234567'},
            tenant_id='t1',
            supabase=self.supabase,
            meli_order_id='ord-AB',
        )
        # Buscar la llamada a 'consent_audit_log'.
        audit_calls = [
            c for c in self.supabase.table.call_args_list
            if c.args and c.args[0] == 'consent_audit_log'
        ]
        self.assertGreater(len(audit_calls), 0,
                           'consent_audit_log debió ser invocado')

        # Validar shape del insert.
        audit_payload = self.insert_chain.call_args_list[-1].args[0]
        self.assertEqual(audit_payload['event'], 'granted')
        self.assertEqual(audit_payload['source'], 'system')
        self.assertEqual(audit_payload['tenant_id'], 't1')
        self.assertEqual(audit_payload['contact_id'], 'contact-uuid-123')
        self.assertIsNotNone(audit_payload['phone_hash'])
        self.assertEqual(len(audit_payload['phone_hash']), 64)  # sha256 hex
        self.assertEqual(audit_payload['actor_email'], 'system:meli_webhook')
        self.assertEqual(
            audit_payload['evidence']['meli_order_id'], 'ord-AB',
        )
        self.assertEqual(
            audit_payload['evidence']['imported_from'], 'mercadolibre',
        )

    def test_audit_failure_does_not_abort_upsert(self):
        # Configurar audit log para fallar; el SELECT legacy retorna vacío.
        def selective_table(name):
            tbl = MagicMock()
            if name == 'consent_audit_log':
                tbl.insert.return_value.execute.side_effect = Exception('boom')
            else:
                # Legacy SELECT empty → upsert path.
                tbl.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
                tbl.upsert.return_value.execute.return_value = MagicMock(
                    data=[{'id': 'cid-1'}],
                )
            return tbl
        self.supabase.table.side_effect = selective_table

        # Aún con audit log roto, debe retornar el contact_id.
        result = _upsert_meli_contact(
            buyer={'first_name': 'X', 'phone': '3001234567'},
            tenant_id='t1',
            supabase=self.supabase,
            meli_order_id='ord-fail',
        )
        self.assertEqual(result, 'cid-1')

    def test_legacy_phone_migrates_to_canonical(self):
        # Rev. 104 (F0-4): si existe un contact con phone legacy en formato
        # E.164 (con `+`), el webhook UPDATEa esa fila con phone canónico
        # (digits-only) + payload, evitando duplicados.
        # NOTA: el escenario invertido vs rev. 103 — antes el legacy era
        # "sin +" y migraba a "con +". Ahora el legacy es "con +" y migra
        # a "sin +" (canon).
        contacts_tbl = MagicMock()
        contacts_tbl.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{'id': 'legacy-cid-7'}],
        )
        audit_tbl = MagicMock()
        audit_tbl.insert.return_value.execute.return_value = MagicMock()
        def selective_table(name):
            return audit_tbl if name == 'consent_audit_log' else contacts_tbl
        self.supabase.table.side_effect = selective_table

        result = _upsert_meli_contact(
            buyer={'first_name': 'X', 'phone': '3009999999'},
            tenant_id='t1',
            supabase=self.supabase,
            meli_order_id='ord-legacy',
        )
        self.assertEqual(result, 'legacy-cid-7')
        # update fue llamado con phone canónico (digits-only con prefix CO).
        update_payload = contacts_tbl.update.call_args[0][0]
        self.assertEqual(update_payload['phone'], '573009999999')
        # NO se invocó upsert (path de migración, no de inserción nueva).
        contacts_tbl.upsert.assert_not_called()

    def test_billing_info_phone_is_preferred(self):
        _upsert_meli_contact(
            buyer={
                'phone': '3001111111',
                'billing_info': {'phone': '3009999999'},
            },
            tenant_id='t1',
            supabase=self.supabase,
        )
        upsert_payload = self.upsert_chain.call_args[0][0]
        # Rev. 104 (F0-4): phone canónico (digits-only con prefix CO).
        self.assertEqual(upsert_payload['phone'], '573009999999')


class MigrationMarketplaceMeliTests(unittest.TestCase):
    """La migración añade 'marketplace_meli' al CHECK constraint."""

    def setUp(self):
        path = REPO / 'supabase/migrations/20260510011000_contacts_consent_source_marketplace.sql'
        self.sql = path.read_text()

    def test_drops_old_constraint(self):
        self.assertIn(
            'DROP CONSTRAINT IF EXISTS contacts_consent_source_check',
            self.sql,
        )

    def test_adds_marketplace_meli_value(self):
        self.assertIn("'marketplace_meli'", self.sql)

    def test_preserves_existing_sources(self):
        for src in ('manual_console', 'whatsapp', 'web_form', 'phone_call',
                    'in_person', 'import', 'other'):
            self.assertIn(f"'{src}'", self.sql)


class PrivacyPolicySectionTests(unittest.TestCase):
    """§10 marketplace en la política de privacidad."""

    def test_section_10_marketplace_exists(self):
        path = REPO / 'docs/legal/privacy-policy.md'
        text = path.read_text()
        self.assertIn('## 10. Datos importados desde marketplaces', text)
        self.assertIn('marketplace_meli', text)


if __name__ == '__main__':
    unittest.main()
