"""Cliente HTTP Aveonline — auth v1.0 + cotización + tracking + label.

Rev. 107 M.1 — primer release del cliente. Cubre el subset crítico para
que el agentic orchestrator pueda cotizar con Aveonline cuando
`tenant_shipping_provider_config.active_provider = 'aveonline'`.

Auth: usuario+password POR TENANT (Vault) → JWT cacheado en
`tenant_integrations.credentials.jwt_token`. Refresh automático si
expira_at < now + buffer 10min.

Endpoints implementados (M.1.a):
  • `auth.aveonline.co/api/comunes/v1.0/autenticarusuario.php` (refresh JWT).
  • `webservices.aveonline.co/cotizar/cotizar.php` (cotizarDoble — multi-carrier).

Pendientes M.1.b (próximas sesiones):
  • `generarGuiaTransporteNacional` (label).
  • `consultarGuias` (tracking).
  • `cancelarGuia` (cancel).
  • `solicitudRecogida` (pickup).

Referencia: docs/research/aveonline-dossier.md (versión 101%).

Manejo de errores (mapeo numbererror per §14 dossier):
  • -1 generic → ErrorAveonlineTransient (retry).
  • -2 credenciales → ErrorAveonlineAuth (refresh JWT + retry 1 vez).
  • -3 sin carriers → ErrorAveonlineNoCarriers (mensaje al cliente).
  • -5 valor declarado < 10k → auto-corrección a 10k mínimo.
  • -7 peso máx excedido → ErrorAveonlinePackageLimit.
  • 999 bug `cotizar2` → IGNORADO (usamos `cotizarDoble` siempre).
  • HTTP 5xx → ErrorAveonlineTransient (retry).
  • HTTP 4xx ≠ 429 → ErrorAveonlinePermanent (no retry).
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


# ─── URLs oficiales (dossier §1) ──────────────────────────────────────────

AVEONLINE_AUTH_URL = (
    "https://app.aveonline.co/api/comunes/v1.0/autenticarusuario.php"
)
# Endpoint genérico nacional: mismo URL para cotizar/generarGuia/recogida.
# El discriminador es el campo `tipo` del body. Para cotización
# multi-carrier usamos `tipo: "cotizarDoble"` (dossier §3.2 — recomendado
# por plugin WooCommerce oficial). NUNCA `tipo: "cotizar2"` (causa del
# bug 999 documentado en TL;DR del dossier).
AVEONLINE_NAL_URL = (
    "https://app.aveonline.co/api/nal/v1.0/generarGuiaTransporteNacional.php"
)

# Timeouts (dossier §15.5: plugin oficial usa CURLOPT_TIMEOUT=0; nosotros
# preferimos 25s — Envia tiene mismo orden de magnitud).
AVEONLINE_TIMEOUT_SECONDS = 25.0

# Buffer JWT refresh (refresh si expira_at < now + 10min).
JWT_REFRESH_BUFFER_SECONDS = 600

# Cache idempotency local cotización (replica plugin oficial 60s).
QUOTE_CACHE_TTL_SECONDS = 60


# ─── Excepciones tipadas ──────────────────────────────────────────────────


class AveonlineError(Exception):
    """Base — todas las excepciones Aveonline heredan de aquí."""


class AveonlineAuthError(AveonlineError):
    """Credenciales inválidas o JWT expirado sin posibilidad de refresh."""


class AveonlineTransientError(AveonlineError):
    """Error transitorio (5xx, network) — caller puede reintentar."""


class AveonlinePermanentError(AveonlineError):
    """Error permanente (4xx no transitorio, bug schema) — NO retry."""


class AveonlineNoCarriersError(AveonlineError):
    """Sin transportadoras disponibles para ruta — mensaje al cliente."""


class AveonlinePackageLimitError(AveonlineError):
    """Paquete excede peso/dim máximo de carriers — el cliente debe dividir."""


# ─── DTOs ──────────────────────────────────────────────────────────────────


@dataclass
class QuoteOption:
    """Una opción de cotización retornada por cotizarDoble."""
    rate_id: str            # id interno aveonline (idtransportadora)
    carrier_name: str       # e.g. "Coordinadora Mercantil"
    service_level: str      # e.g. "estandar" / "expreso"
    price_cents: int        # total COP * 100
    eta_days: Optional[int] # días estimados de entrega
    raw: dict               # response cruda por carrier (para audit)


@dataclass
class QuoteResult:
    """Resultado completo de quote()."""
    options: list[QuoteOption]
    origin_dane: str
    destination_dane: str
    cache_hit: bool
    raw_response: dict


# ─── Cliente principal ───────────────────────────────────────────────────


class AveonlineClient:
    """Cliente HTTP Aveonline scoped a un tenant.

    Uso:
        client = AveonlineClient(tenant_id, supabase_client)
        result = await client.quote(
            origin={"dane": "11001", "city": "Bogotá"},
            destination={"dane": "05001", "city": "Medellín"},
            package={"weight_kg": 0.5, "length_cm": 15,
                     "width_cm": 10, "height_cm": 3,
                     "declared_value_cop": 35000, "units": 1},
        )
        for opt in result.options:
            print(f"{opt.carrier_name}: ${opt.price_cents/100}")
    """

    def __init__(self, tenant_id: str, supabase: Any):
        self.tenant_id = tenant_id
        self.supabase = supabase
        self._credentials_cache: Optional[dict] = None
        # In-memory idempotency cache (key=hash, value=(QuoteResult, ts)).
        self._quote_cache: dict[str, tuple[QuoteResult, float]] = {}

    # ─── Auth + credentials ───────────────────────────────────────────────

    async def _load_credentials(self, force_refresh: bool = False) -> dict:
        """Carga credenciales (con password resuelto via Vault) usando el
        RPC `get_aveonline_credentials` creado en migración 20260527020000.

        Returns:
            dict con campos: usuario, password (resuelto), empresa_id,
            jwt_token, jwt_expires_at, tiempo_token, auth_version.
        """
        if self._credentials_cache and not force_refresh:
            return self._credentials_cache

        res = self.supabase.rpc(
            "get_aveonline_credentials",
            {"p_tenant_id": self.tenant_id},
        ).execute()
        creds = res.data
        if not creds:
            raise AveonlineAuthError(
                f"Tenant {self.tenant_id} no tiene Aveonline configurado "
                f"(o status != 'connected'). Configura en "
                f"/dashboard/integrations/aveonline."
            )
        self._credentials_cache = creds
        return creds

    def _jwt_expired(self, creds: dict) -> bool:
        """True si el JWT necesita refresh (con buffer)."""
        expires_at_raw = creds.get("jwt_expires_at")
        if not expires_at_raw:
            return True
        try:
            expires_at = datetime.fromisoformat(
                expires_at_raw.replace("Z", "+00:00")
            )
        except (ValueError, AttributeError):
            return True
        now = datetime.now(timezone.utc)
        return expires_at < now + timedelta(seconds=JWT_REFRESH_BUFFER_SECONDS)

    async def _refresh_jwt(self) -> str:
        """Re-autentica con Aveonline + persiste nuevo JWT en DB.

        Returns:
            JWT fresco.

        Raises:
            AveonlineAuthError si credenciales rechazadas por Aveonline.
            AveonlineTransientError si Aveonline 5xx.
        """
        creds = await self._load_credentials(force_refresh=True)
        usuario = creds.get("usuario")
        password = creds.get("password")
        tiempo_token = int(creds.get("tiempo_token") or 100000)

        if not usuario or not password:
            raise AveonlineAuthError(
                "Credenciales incompletas (falta usuario/password) en Vault."
            )

        body = {
            "tipo": "auth",
            "usuario": usuario,
            "clave": password,
            "acceso": "ecommerce",
            "tiempoToken": tiempo_token,
        }
        try:
            async with httpx.AsyncClient(timeout=AVEONLINE_TIMEOUT_SECONDS) as cx:
                resp = await cx.post(AVEONLINE_AUTH_URL, json=body)
        except httpx.HTTPError as exc:
            raise AveonlineTransientError(f"auth network error: {exc}")

        if resp.status_code >= 500:
            raise AveonlineTransientError(
                f"Aveonline auth HTTP {resp.status_code}"
            )
        if resp.status_code != 200:
            raise AveonlinePermanentError(
                f"Aveonline auth HTTP {resp.status_code}: {resp.text[:200]}"
            )

        data = resp.json()
        if data.get("status") != "ok" or not data.get("token"):
            raise AveonlineAuthError(
                f"Aveonline rechazó credenciales: {data.get('message', 'unknown')}"
            )

        new_jwt = data["token"]
        new_expires = (
            datetime.now(timezone.utc) + timedelta(seconds=tiempo_token)
        ).isoformat()

        # Persistir en DB via RPC (migración 20260527020000).
        self.supabase.rpc(
            "upsert_aveonline_jwt",
            {
                "p_tenant_id": self.tenant_id,
                "p_jwt_token": new_jwt,
                "p_jwt_expires_at": new_expires,
            },
        ).execute()

        # Actualizar cache local.
        creds["jwt_token"] = new_jwt
        creds["jwt_expires_at"] = new_expires
        self._credentials_cache = creds

        logger.info(
            "[aveonline.auth] tenant=%s JWT refresh OK expires=%s",
            self.tenant_id[:8], new_expires[:19],
        )
        return new_jwt

    async def _get_valid_jwt(self) -> str:
        """Retorna JWT válido (refresh si expirado)."""
        creds = await self._load_credentials()
        if self._jwt_expired(creds):
            return await self._refresh_jwt()
        return creds["jwt_token"]

    # ─── Quote (cotizarDoble) ─────────────────────────────────────────────

    def _hash_quote_request(
        self, origin: dict, destination: dict, package: dict,
    ) -> str:
        """Hash determinístico del request para idempotency cache."""
        canonical = {
            "o": origin.get("dane"),
            "d": destination.get("dane"),
            "w": package.get("weight_kg"),
            "l": package.get("length_cm"),
            "wd": package.get("width_cm"),
            "h": package.get("height_cm"),
            "v": package.get("declared_value_cop"),
            "u": package.get("units", 1),
            "c": package.get("cod_enabled", False),
        }
        return hashlib.sha256(
            json.dumps(canonical, sort_keys=True).encode()
        ).hexdigest()

    async def quote(
        self,
        origin: dict,
        destination: dict,
        package: dict,
    ) -> QuoteResult:
        """Cotiza envío multi-carrier vía cotizarDoble.

        Args:
            origin: {"dane": str, "city": str}
            destination: {"dane": str, "city": str}
            package: {
                "weight_kg": float,
                "length_cm": float,
                "width_cm": float,
                "height_cm": float,
                "declared_value_cop": int (min 10000),
                "units": int (default 1),
                "cod_enabled": bool (default False),
            }

        Returns:
            QuoteResult con .options list (puede estar vacía si numbererror=-3).

        Raises:
            AveonlineAuthError, AveonlinePermanentError, AveonlineTransientError,
            AveonlineNoCarriersError, AveonlinePackageLimitError.
        """
        # Cache lookup (idempotency 60s).
        # IMPORTANTE: retornamos un nuevo QuoteResult copia, no mutamos el
        # cached object. Si mutamos `cached.cache_hit = True`, el primer
        # retorno también se marcaría como cache_hit (mismo objeto referenciado).
        cache_key = self._hash_quote_request(origin, destination, package)
        cached = self._quote_cache.get(cache_key)
        if cached:
            cached_result, ts = cached
            if time.time() - ts < QUOTE_CACHE_TTL_SECONDS:
                logger.info(
                    "[aveonline.quote] tenant=%s cache HIT key=%s",
                    self.tenant_id[:8], cache_key[:8],
                )
                return QuoteResult(
                    options=cached_result.options,
                    origin_dane=cached_result.origin_dane,
                    destination_dane=cached_result.destination_dane,
                    cache_hit=True,
                    raw_response=cached_result.raw_response,
                )

        # Auto-corrección valor declarado < 10k (regla AveCRM §3.10.1).
        declared = max(10000, int(package.get("declared_value_cop") or 10000))

        jwt = await self._get_valid_jwt()
        creds = await self._load_credentials()
        empresa_id = creds.get("empresa_id")
        # `idagente` (dirección de despacho) es REQUERIDO según §3.5 del
        # dossier — sin él algunas transportadoras retornan 999. Se intenta
        # leer de credentials.idagente (poblar en O.3 si Aveonline lo retorna
        # en auth response, o config manual desde panel tenant).
        idagente = creds.get("idagente") or creds.get("asesor_logistico") or ""

        # Body canónico §3.3 dossier — campos en lugar correcto:
        #   • `idempresa` (no `empresa`).
        #   • Dimensiones DENTRO de `productos[]` (no top-level).
        #   • Origen/destino: formato UPPERCASE "BOGOTA(CUNDINAMARCA)" o
        #     codigoDANE 8 dígitos. El caller pasa lo que tenga (city o dane).
        body = {
            "tipo": "cotizarDoble",
            "access": "",  # compat legacy
            "token": jwt,
            "idempresa": empresa_id,
            "idagente": idagente,
            "origen": str(
                origin.get("city_canonical")
                or origin.get("dane")
                or origin.get("city")
                or ""
            ),
            "destino": str(
                destination.get("city_canonical")
                or destination.get("dane")
                or destination.get("city")
                or ""
            ),
            "idasumecosto": 0,
            "contraentrega": 1 if package.get("cod_enabled") else 0,
            "contraentregaPayment": 0,
            "valorrecaudo": 0,
            "valorMinimo": 0,
            "productos": [{
                "alto": float(package.get("height_cm") or 10),
                "largo": float(package.get("length_cm") or 10),
                "ancho": float(package.get("width_cm") or 10),
                "peso": float(package.get("weight_kg") or 1.0),
                "unidades": int(package.get("units", 1)),
                "nombre": str(package.get("product_name") or "Producto"),
                "valorDeclarado": declared,
            }],
            "plugin": "konvi",
        }

        try:
            async with httpx.AsyncClient(timeout=AVEONLINE_TIMEOUT_SECONDS) as cx:
                resp = await cx.post(AVEONLINE_NAL_URL, json=body)
        except httpx.HTTPError as exc:
            raise AveonlineTransientError(f"quote network error: {exc}")

        if resp.status_code >= 500:
            raise AveonlineTransientError(
                f"Aveonline quote HTTP {resp.status_code}"
            )
        if resp.status_code != 200:
            raise AveonlinePermanentError(
                f"Aveonline quote HTTP {resp.status_code}: {resp.text[:200]}"
            )

        data = resp.json()

        # Aveonline puede retornar HTTP 200 con `status="error"` global o por
        # carrier (numbererror per fila).
        if isinstance(data, dict) and data.get("status") == "error":
            self._raise_for_numbererror(data.get("numbererror"), data.get("message"))

        # Parsear opciones. cotizarDoble retorna array `cotizaciones` (campo
        # canónico verificado contra response real DEMO 2026-05-22). Variantes
        # legacy: `opciones`/`data` se aceptan por compat futura.
        raw_options = (
            data.get("cotizaciones")
            or data.get("opciones")
            or data.get("data")
            or []
        )
        if not isinstance(raw_options, list):
            raise AveonlinePermanentError(
                f"Schema inesperado: cotizaciones no es array. Got: {type(raw_options).__name__}"
            )

        # Schema real de `cotizaciones[]` (verificado contra response DEMO
        # 2026-05-22, ruta Bogotá→Medellín): cada fila tiene
        # `codTransportadora`, `nombreTransportadora`, `numbererror`, `total`,
        # `diasentrega` (string), `valoracion`, `pesovolumen`, `tipoEnvio`,
        # `trayecto`, etc. Aceptamos también nombres legacy por compat.
        options: list[QuoteOption] = []
        for row in raw_options:
            if not isinstance(row, dict):
                continue
            # Filtrar errores por carrier (numbererror != "-0-" significa fallo).
            ne = str(row.get("numbererror") or "").strip()
            if ne and ne != "-0-":
                continue
            total = row.get("total") or row.get("totalPrice") or 0
            try:
                price_cents = int(float(total) * 100)
            except (TypeError, ValueError):
                continue
            if price_cents <= 0:
                continue
            options.append(QuoteOption(
                rate_id=str(
                    row.get("codTransportadora")
                    or row.get("idtransportadora")
                    or row.get("id")
                    or ""
                ),
                carrier_name=str(
                    row.get("nombreTransportadora")
                    or row.get("transportadora")
                    or row.get("carrier")
                    or ""
                ),
                service_level=str(
                    row.get("tipoEnvio")
                    or row.get("servicio")
                    or "estandar"
                ),
                price_cents=price_cents,
                eta_days=self._parse_eta(row),
                raw=row,
            ))

        if not options:
            raise AveonlineNoCarriersError(
                f"Aveonline retornó 0 opciones para "
                f"{origin.get('city')} → {destination.get('city')}. "
                f"Posibles causas: ruta sin cobertura, carriers no "
                f"contratados, peso/dimensiones fuera de rango."
            )

        result = QuoteResult(
            options=options,
            origin_dane=str(origin.get("dane") or ""),
            destination_dane=str(destination.get("dane") or ""),
            cache_hit=False,
            raw_response=data,
        )

        # Persist en cache.
        self._quote_cache[cache_key] = (result, time.time())
        # Evict si crece demasiado.
        if len(self._quote_cache) > 128:
            oldest = min(
                self._quote_cache.keys(),
                key=lambda k: self._quote_cache[k][1],
            )
            self._quote_cache.pop(oldest, None)

        logger.info(
            "[aveonline.quote] tenant=%s OK options=%d origin=%s dest=%s",
            self.tenant_id[:8], len(options),
            origin.get("city"), destination.get("city"),
        )
        return result

    # ─── Helpers ──────────────────────────────────────────────────────────

    def _raise_for_numbererror(
        self, code: Any, message: Optional[str] = None,
    ) -> None:
        """Mapea numbererror → excepción tipada (dossier §14.2)."""
        c = str(code or "").strip()
        msg = message or f"Aveonline numbererror={c}"
        if c in ("-1",):
            raise AveonlineTransientError(msg)
        if c in ("-2",):
            raise AveonlineAuthError(msg)
        if c in ("-3",):
            raise AveonlineNoCarriersError(msg)
        if c in ("-7",):
            raise AveonlinePackageLimitError(msg)
        if c in ("999",):
            # Bug `cotizar2` — no debería pasar con cotizarDoble.
            raise AveonlinePermanentError(
                f"Bug 999 inesperado en cotizarDoble: {msg}"
            )
        # Default: tratar como permanente.
        raise AveonlinePermanentError(msg)

    @staticmethod
    def _parse_eta(rate_row: dict) -> Optional[int]:
        """Extrae días de entrega del response.

        Schema real Aveonline: `diasentrega` como string (e.g. "3"). Fallback
        a campos legacy `tiempoEntrega`/`dias` por compat futura."""
        for key in ("diasentrega", "tiempoEntrega", "dias", "eta_days", "deliveryDays"):
            v = rate_row.get(key)
            if v is None or v == "" or v == "000":
                continue
            try:
                return int(v)
            except (TypeError, ValueError):
                continue
        return None
