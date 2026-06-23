"""
VaultHelper — lectura/escritura de secretos via Supabase Vault.

⚠️ COPIED 2026-06-22 from `services/api/vault_helper.py` para Model B Direct Provider
   per-tenant (ADR-0023). Mantener en sync con la fuente. TODO: consolidar Sem 12
   en un paquete compartido `packages/secrets/` cuando se haga finiquito A6.

Usa RPCs pgsec_* definidas en la migración 20260426020000.
Soporta fallback a texto plano para compatibilidad durante ventana de migración.
"""
import logging
from typing import Optional

from supabase import Client

logger = logging.getLogger(__name__)


class VaultHelper:
    def __init__(self, supabase: Client) -> None:
        self._sb = supabase

    def create_secret(self, secret: str, name: str, description: str = "") -> Optional[str]:
        """Guarda un secreto en Vault. Si el nombre ya existe, actualiza el valor.
        Retorna UUID o None si falla."""
        try:
            r = self._sb.rpc("pgsec_upsert_secret", {
                "p_secret": secret, "p_name": name, "p_description": description,
            }).execute()
            return str(r.data) if r.data else None
        except Exception as e:
            logger.error("[VAULT] upsert '%s' error: %s", name, e)
            return None

    def read_secret(self, secret_id: Optional[str]) -> Optional[str]:
        """Lee un secreto de Vault por su UUID."""
        if not secret_id:
            return None
        try:
            r = self._sb.rpc("pgsec_read_secret", {"p_id": secret_id}).execute()
            return r.data
        except Exception as e:
            logger.error("[VAULT] read '%s' error: %s", secret_id, e)
            return None

    def update_secret(self, secret_id: str, new_secret: str) -> bool:
        """Actualiza un secreto existente en Vault."""
        try:
            r = self._sb.rpc("pgsec_update_secret", {
                "p_id": secret_id, "p_secret": new_secret,
            }).execute()
            return bool(r.data)
        except Exception as e:
            logger.error("[VAULT] update '%s' error: %s", secret_id, e)
            return False

    def delete_secret(self, secret_id: Optional[str]) -> bool:
        """Elimina un secreto de Vault. No-op si secret_id es None."""
        if not secret_id:
            return True
        try:
            self._sb.rpc("pgsec_delete_secret", {"p_id": secret_id}).execute()
            return True
        except Exception as e:
            logger.error("[VAULT] delete '%s' error: %s", secret_id, e)
            return False


def resolve_secret(vault: VaultHelper, creds: dict, field: str) -> Optional[str]:
    """
    Resuelve un campo de credencial: Vault primero, texto plano como fallback.
    Vault:      creds = {'field_secret_id': 'uuid'}
    Legado:     creds = {'field': 'plain_value'}
    """
    secret_id = creds.get(f"{field}_secret_id")
    if secret_id:
        return vault.read_secret(secret_id)
    plain = creds.get(field)
    if plain:
        logger.warning("[VAULT] '%s' en texto plano — migrar a Vault recomendado", field)
    return plain
