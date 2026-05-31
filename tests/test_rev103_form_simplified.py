"""Rev. 103 (SaaS B2B pivot) — Tests del form Add/Edit simplificado.

Filosofía:
  • La plataforma es Encargado puro (modelo Wati/Mailchimp/Respond.io).
  • El tenant es Responsable; firma DPA y certifica base legal de los
    datos que registra.
  • El form NO bloquea PII sin consent. Si el operador llena PII sin
    marcar consent, persistimos con consent_given=false; el bot pedirá
    consent al titular en su próxima interacción WhatsApp.

Cobertura (lectura de fuente, no test de runtime):
  • CONSENT_SOURCES tiene los 8 canales esperados (manual_console y
    phone_call restaurados; marketplace_meli añadido).
  • Server actions addContact/editContact NO contienen los guards
    PII-sin-consent de rev. 102.
  • El form Add NO contiene `disabled={!addConsentChecked}`.
  • El piiUnlocked en form Edit solo gatea el caso post-anonimización
    (Art. 15 ritual legal sigue intacto).
  • CONSENT_SOURCE_HELP cubre los 7 canales operacionales (todos menos
    marketplace_meli, que no se ofrece en UI).
"""
from pathlib import Path
import unittest

REPO = Path('/home/ansible/workspaces/konvi-platform')
PAGE_TSX = REPO / 'apps/web/app/dashboard/(sales)/contacts/page.tsx'
MANAGER_TSX = REPO / 'apps/web/app/dashboard/(sales)/contacts/_components/contacts-manager.tsx'
CONSENT_HELP_TS = REPO / 'apps/web/app/dashboard/(sales)/contacts/_components/helpers/consent-source-help.ts'


class ConsentSourcesRev103Tests(unittest.TestCase):
    """CONSENT_SOURCES restaurado a los 8 canales (incluye marketplace_meli)."""

    def setUp(self):
        self.page_src = PAGE_TSX.read_text()

    def test_manual_console_restored(self):
        self.assertIn("'manual_console'", self.page_src)

    def test_phone_call_restored(self):
        self.assertIn("'phone_call'", self.page_src)

    def test_marketplace_meli_added(self):
        self.assertIn("'marketplace_meli'", self.page_src)

    def test_all_seven_operational_channels_in_set(self):
        # Set declarado a nivel módulo: contiene los 8 canales válidos.
        for canal in ('manual_console', 'whatsapp', 'web_form', 'phone_call',
                      'in_person', 'import', 'other', 'marketplace_meli'):
            self.assertIn(f"'{canal}'", self.page_src,
                          f"Canal {canal} debería estar en CONSENT_SOURCES")


class ServerActionsRev103Tests(unittest.TestCase):
    """Guards PII-sin-consent eliminados; soft-revoke + Art. 15 mantenidos."""

    def setUp(self):
        self.page_src = PAGE_TSX.read_text()

    def test_no_pii_attempted_guard_in_add(self):
        # Rev. 102 throw: 'No se pueden registrar datos personales sin consentimiento'
        # debe haber sido eliminado del addContact.
        self.assertNotIn(
            'No se pueden registrar datos personales sin consentimiento',
            self.page_src,
        )

    def test_no_pii_persisted_guard_in_edit(self):
        # Rev. 102 throw: 'No se pueden persistir datos personales sin consentimiento'
        # debe haber sido eliminado del editContact.
        self.assertNotIn(
            'No se pueden persistir datos personales sin consentimiento',
            self.page_src,
        )

    def test_soft_revoke_guard_preserved(self):
        # El guard "no puedes desmarcar el check para revocar" SÍ se mantiene
        # (la revocación va por Anonimizar — Art. 15 ritual legal serio).
        self.assertIn(
            'No puedes revocar el consentimiento desmarcando este check',
            self.page_src,
        )

    def test_other_evidence_min_20_chars_guard_preserved(self):
        # Canal "other" sigue exigiendo Evidencia ≥ 20 chars.
        self.assertIn('canal es "Otro"', self.page_src)

    def test_renewed_consent_post_anonim_guard_preserved(self):
        # Re-introducir PII tras anonimización requiere renewed_consent
        # con evidencia ≥ 10 chars (Art. 15 ritual).
        self.assertIn(
            'al menos 10 caracteres',
            self.page_src,
        )


class FormAddRev103Tests(unittest.TestCase):
    """Form Add: PII inputs ya NO están gated por addConsentChecked."""

    def setUp(self):
        self.manager_src = MANAGER_TSX.read_text()

    def test_no_disabled_addconsent_in_add_form(self):
        # Rev. 102 ataba name/email/notes a `disabled={!addConsentChecked}`.
        # En rev. 103 el operador llena lo que necesita; consent es info.
        self.assertNotIn(
            'disabled={!addConsentChecked}',
            self.manager_src,
        )

    def test_no_blocked_marker_in_add_form(self):
        # Mensajes "Documento de identidad bloqueado — marca el consentimiento"
        # del form Add fueron eliminados.
        self.assertNotIn(
            'Documento de identidad bloqueado — marca el consentimiento',
            self.manager_src,
        )
        self.assertNotIn(
            'Dirección bloqueada — marca el consentimiento',
            self.manager_src,
        )

    def test_no_amber_warning_banner_in_add_form(self):
        # Banner amber "Marca el check de consentimiento más abajo para
        # habilitar los campos personales" eliminado.
        self.assertNotIn(
            'Marca el check de consentimiento más abajo para habilitar los',
            self.manager_src,
        )


class FormEditRev103Tests(unittest.TestCase):
    """Form Edit: piiUnlocked solo gatea post-anonimización (Art. 15)."""

    def setUp(self):
        self.manager_src = MANAGER_TSX.read_text()

    def test_pii_unlocked_only_gates_awaiting_renewal(self):
        # Rev. 103 lógica: piiUnlocked = !awaitingRenewal || !!renewedConsent[c.id]
        # No debe seguir dependiendo de consentChecked en el caso normal.
        self.assertIn(
            'const piiUnlocked = !awaitingRenewal || !!renewedConsent[c.id]',
            self.manager_src,
        )

    def test_post_anonim_block_message_preserved(self):
        # Cuando awaitingRenewal=true y no hay renewed_consent, los
        # mensajes "confirma consentimiento renovado para editar" deben
        # seguir apareciendo (Art. 15).
        self.assertIn(
            'confirma consentimiento renovado para editar',
            self.manager_src,
        )


class ConsentSourceHelpRev103Tests(unittest.TestCase):
    """Help text contextual cubre los 7 canales operacionales.

    Bloque 4 — extraído de contacts-manager.tsx a
    `helpers/consent-source-help.ts`.
    """

    def setUp(self):
        self.help_src = CONSENT_HELP_TS.read_text()

    def test_help_includes_manual_console(self):
        self.assertIn('manual_console:', self.help_src)

    def test_help_includes_phone_call(self):
        self.assertIn('phone_call:', self.help_src)

    def test_help_includes_all_ui_channels(self):
        # Los 7 canales que aparecen en el dropdown UI tienen help.
        # marketplace_meli NO aparece (solo via webhook MeLi).
        for canal in ('manual_console', 'whatsapp', 'web_form', 'phone_call',
                      'in_person', 'import', 'other'):
            self.assertIn(f'{canal}:', self.help_src,
                          f'Help text faltante para canal {canal}')


class DropdownOptionsRev103Tests(unittest.TestCase):
    """Dropdown UI ofrece los 7 canales operacionales (no marketplace_meli)."""

    def setUp(self):
        self.manager_src = MANAGER_TSX.read_text()

    def test_dropdown_offers_manual_console(self):
        self.assertIn('<option value="manual_console">', self.manager_src)

    def test_dropdown_offers_phone_call(self):
        self.assertIn('<option value="phone_call">', self.manager_src)

    def test_dropdown_does_not_offer_marketplace_meli(self):
        # marketplace_meli es solo via webhook MeLi backend.
        self.assertNotIn('<option value="marketplace_meli">', self.manager_src)


if __name__ == '__main__':
    unittest.main()
