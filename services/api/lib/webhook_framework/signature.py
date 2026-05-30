"""Webhook signature strategies (rev. 105 Sem 2 F.1).

Implementa los 4 patrones documentados en meta-análisis cross-dossier 2026-05-05:

  1. **HMAC SHA-256** (Meta WhatsApp)
     - Header `X-Hub-Signature-256: sha256=<hex>`
     - HMAC sobre raw body con app_secret per tenant.

  2. **SHA256 plain** (Wompi)
     - Header `events_key` o body['signature']['checksum']
     - SHA256(properties_concat + timestamp + events_key)
     - NO es HMAC formal — es checksum determinístico documentado por Wompi.

  3. **URL secret-token** (Telegram, Envia, otros sin firma nativa)
     - Header `X-Telegram-Bot-Api-Secret-Token` (Telegram) o query param
       `?secret=...` (Envia HMAC propio rotable F.10).
     - Comparación constant-time contra secret_hash (bcrypt verify para F.10
       o token plain comparado contra cache para Telegram).

  4. **IP allowlist** (MeLi, defensa segunda Wompi)
     - Verificación `request.client.host in ALLOWLIST`.
     - Combinable con otros strategies (defensa-en-profundidad).

Uso (en concrete handler):
    class MetaWebhookHandler(WebhookHandler):
        signature_strategy = HMACSha256Strategy(
            header_name="X-Hub-Signature-256",
            secret_resolver=lambda headers, raw_body: resolve_meta_app_secret_per_tenant(raw_body),
        )
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
from abc import ABC, abstractmethod
from typing import Any, Callable, Optional

from .errors import SignatureError


class SignatureStrategy(ABC):
    """Contrato abstracto para verificación de firma webhook."""

    @abstractmethod
    def verify(
        self,
        *,
        raw_body: bytes,
        headers: dict[str, str],
        query_params: dict[str, str],
        client_ip: Optional[str] = None,
    ) -> None:
        """Verifica firma. Levanta SignatureError si falla. Retorna None si OK."""


class HMACSha256Strategy(SignatureStrategy):
    """HMAC SHA-256 con header configurable. Patrón Meta WhatsApp.

    Header puede venir con prefijo (`sha256=<hex>`) — se strip automáticamente.
    Comparación constant-time vía hmac.compare_digest.

    `secret_resolver(headers, raw_body) → str`: rev. 2026-05-08 (Sem 6 pre-HSM)
    la signature del resolver se extiende a `(headers, raw_body)` para casos
    multi-tenant donde el secret se resuelve via lookup en payload (ej. Meta
    WhatsApp: `phone_number_id` viene en `entry[].changes[].value.metadata`
    → lookup tenant_id → app_secret per-tenant via F.11). Callers que sólo
    necesiten headers ignoran `raw_body` (parámetro positional).
    """

    def __init__(
        self,
        *,
        header_name: str = "X-Hub-Signature-256",
        secret_resolver: Callable[[dict[str, str], bytes], str],
        prefix: str = "sha256=",
    ):
        self._header = header_name.lower()
        self._secret_resolver = secret_resolver
        self._prefix = prefix

    def verify(self, *, raw_body, headers, query_params, client_ip=None):
        # Headers normalized lowercase.
        norm_headers = {k.lower(): v for k, v in headers.items()}
        sig_received = norm_headers.get(self._header, "")
        if not sig_received:
            raise SignatureError(f"Missing header {self._header}")
        if self._prefix and sig_received.startswith(self._prefix):
            sig_received = sig_received[len(self._prefix):]

        secret = self._secret_resolver(norm_headers, raw_body)
        if not secret:
            raise SignatureError("HMAC secret no resuelto para esta request")

        sig_computed = hmac.new(
            secret.encode("utf-8"),
            raw_body,
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(sig_computed, sig_received):
            raise SignatureError("HMAC SHA-256 mismatch")


class WompiChecksumStrategy(SignatureStrategy):
    """SHA256 plain checksum documentado en https://docs.wompi.co/docs/colombia/eventos/

    Wompi NO firma con HMAC formal — emite SHA256(properties_values + timestamp + events_key).
    Properties_values vienen en payload['signature']['properties']: lista de paths
    como 'transaction.id', 'transaction.status'. El handler debe extraer los
    valores en el orden indicado, concatenar como strings, agregar timestamp
    + events_key, hashear y comparar contra payload['signature']['checksum'].
    """

    def __init__(
        self,
        *,
        events_key_resolver: Callable[[dict[str, Any]], str],
    ):
        self._key_resolver = events_key_resolver

    def verify(self, *, raw_body, headers, query_params, client_ip=None):
        # Wompi pone la firma DENTRO del body — necesitamos parsearlo.
        try:
            import json
            payload = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as e:
            raise SignatureError(f"Body no es JSON válido: {e}") from e

        signature_block = payload.get("signature") or {}
        properties = signature_block.get("properties") or []
        checksum_received = signature_block.get("checksum") or ""
        timestamp = str(payload.get("timestamp") or "")

        if not properties or not checksum_received:
            raise SignatureError(
                "Wompi signature block incompleto (properties o checksum vacíos)"
            )

        events_key = self._key_resolver(payload)
        if not events_key:
            raise SignatureError("Wompi events_key no resuelto")

        # Extraer valores de propiedades (paths separados por '.').
        data = payload.get("data") or {}
        concat = ""
        for path in properties:
            value = data
            for part in path.split("."):
                if isinstance(value, dict):
                    value = value.get(part)
                else:
                    value = None
                    break
            concat += str(value) if value is not None else ""

        message = concat + timestamp + events_key
        checksum_computed = hashlib.sha256(message.encode("utf-8")).hexdigest()

        if not hmac.compare_digest(checksum_computed, checksum_received):
            raise SignatureError("Wompi checksum mismatch")


class URLSecretTokenStrategy(SignatureStrategy):
    """URL/header secret-token comparison. Patrón Telegram + Envia (HMAC propio
    via F.10 WebhookSecretManager).

    El token recibido se compara constant-time contra el secret válido
    (resuelto por callback). Para F.10 el callback hace bcrypt verify
    automáticamente con grace period support.
    """

    def __init__(
        self,
        *,
        source: str = "header",  # 'header' | 'query'
        name: str = "X-Telegram-Bot-Api-Secret-Token",
        verifier: Callable[[str], bool],
    ):
        if source not in ("header", "query"):
            raise ValueError(f"source debe ser 'header' o 'query', got {source!r}")
        self._source = source
        self._name = name
        self._verifier = verifier

    def verify(self, *, raw_body, headers, query_params, client_ip=None):
        if self._source == "header":
            received = {k.lower(): v for k, v in headers.items()}.get(
                self._name.lower(), ""
            )
        else:
            received = query_params.get(self._name, "")

        if not received:
            raise SignatureError(
                f"Missing {self._source} {self._name!r}"
            )

        if not self._verifier(received):
            raise SignatureError(
                f"Secret-token verification falló ({self._source} {self._name!r})"
            )


class IPAllowlistStrategy(SignatureStrategy):
    """Verifica que client_ip pertenezca a una lista de redes permitidas.
    Combinable con otras strategies (CompositeStrategy abajo) para
    defensa-en-profundidad. Patrón MeLi (los webhooks vienen desde IPs
    documentadas) y opcionalmente Wompi/Meta.

    Soporta IPv4 + IPv6, redes CIDR (`149.154.160.0/20`), e IPs sueltas.
    """

    def __init__(self, *, allowed_networks: list[str]):
        self._networks: list[ipaddress._BaseNetwork] = []
        for net_str in allowed_networks:
            try:
                self._networks.append(ipaddress.ip_network(net_str, strict=False))
            except ValueError as e:
                raise ValueError(
                    f"Network inválida {net_str!r}: {e}"
                ) from e
        if not self._networks:
            raise ValueError("allowed_networks no puede ser vacía")

    def verify(self, *, raw_body, headers, query_params, client_ip=None):
        if not client_ip:
            raise SignatureError("client_ip no disponible para IP allowlist")
        try:
            ip = ipaddress.ip_address(client_ip)
        except ValueError as e:
            raise SignatureError(f"client_ip inválida {client_ip!r}: {e}") from e
        if not any(ip in net for net in self._networks):
            raise SignatureError(
                f"IP {client_ip} no está en allowlist"
            )


class CompositeStrategy(SignatureStrategy):
    """Combina varias strategies — todas deben pasar (AND lógico).
    Útil para defensa-en-profundidad: HMAC + IP allowlist."""

    def __init__(self, *strategies: SignatureStrategy):
        if not strategies:
            raise ValueError("CompositeStrategy requiere al menos 1 strategy")
        self._strategies = strategies

    def verify(self, *, raw_body, headers, query_params, client_ip=None):
        for strategy in self._strategies:
            strategy.verify(
                raw_body=raw_body,
                headers=headers,
                query_params=query_params,
                client_ip=client_ip,
            )
