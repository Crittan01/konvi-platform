"""
VaultHelper — lectura/escritura de secretos via Supabase Vault.

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
        """Actualiza un secreto existente en Vault. True = RPC ejecutó sin error.

        F63: la RPC `pgsec_update_secret` es RETURNS void (y no-op silencioso si el
        secret no pertenece al tenant, hardening de ownership), así que PostgREST no
        devuelve body. No podemos leer éxito real del retorno; el contrato honesto es
        True si no hubo excepción. Las 3 copias (api/connector/orchestrator) coinciden.
        """
        try:
            self._sb.rpc("pgsec_update_secret", {
                "p_id": secret_id, "p_secret": new_secret,
            }).execute()
            return True
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
