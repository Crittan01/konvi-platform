"""Cliente HTTP Aveonline — auth v1.0 + cotización + guía + tracking + webhook.

Rev. 107 M.1 — primer release del cliente. Conformidad doc oficial verificada
2026-08-22 (fetch devsite + probes live cuenta demo — dossier §26).

Auth: usuario+password POR TENANT (Vault) → JWT cacheado en
`tenant_integrations.credentials.jwt_token`. Refresh automático si
expira_at < now + buffer 10min.

Endpoints implementados:
  • `app.aveonline.co/api/comunes/v1.0/autenticarusuario.php` (refresh JWT).
  • `app.aveonline.co/api/nal/v1.0/generarGuiaTransporteNacional.php`
    (tipos `cotizarDoble` multi-carrier + `generarGuia2` label).
  • `app.aveonline.co/api/comunes/v1.0/agentes.php`
    (`listarAgentesPorEmpresaAuth` — auto-resolución de idagente).
  • `app.aveonline.co/api/box/v1.0/transportadora.php` (carriers por empresa).
  • `app.aveonline.co/api/nal/v1.0/guia.php` (`obtenerEstadoAuth` — tracking pull).
  • `api.aveonline.co/api-integrations/.../custom-webhook` (registro OFICIAL
    del webhook — upsert por empresa; doc `webhookPersonalizadoApi`).
  • `app.aveonline.co/avestock/api/{create,list,delete}Webhook.php` (LEGACY AveCRM).

NO implementados (decisión documentada en dossier §26 / docs/integrations):
  • `generarRecogida2` (recogida programada) — doc existe; feature pendiente (P1.3).
  • `eliminarRelacionEnvios` (batch v2) — no usamos relaciones hoy.
  • Cancelación de guía individual — NO existe por API (reconfirmado 2026-08-22);
    `cancel_guide` queda best-effort no documentado + escalación a operador.

Referencia: docs/research/aveonline-dossier.md (versión 101% + addendum
2026-08-16 API Sandbox + addendum 2026-08-22 conformidad doc vigente).

Manejo de errores (numbererror según tabla OFICIAL vigente — fetch
2026-08-22 de `integraciones.aveonline.co/docs/nacional/cotizacion/`):
  • -1 origen no existe → AveonlinePermanentError (dato inválido, retry inútil).
  • -2 destino no existe → AveonlinePermanentError (idem).
  • -3 peso ≤ 0 → AveonlinePermanentError (bug del caller).
  • -4 unidades ≤ 0 → AveonlinePermanentError (bug del caller).
  • -5 valor declarado < 10k → AveonlinePermanentError (pre-corregido a 10k
    en quote/generate_guide; si aún llega, es bug del caller).
  • -6 unidades > máx → AveonlinePackageLimitError (dividir bultos).
  • -7 kilos > máx → AveonlinePackageLimitError (dividir bultos).
  • 999/-999 servicio no configurado/trayecto inválido → AveonlinePermanentError
    (con `cotizarDoble` llega POR FILA y se filtra; global es bug `cotizar2`).
  • -1000 trayecto con límites (mensaje trae kilosMaximos/unidadesMaximas)
    → AveonlinePackageLimitError.
  • message "credenciales incorrectas"/"autenticacion fallida" →
    AveonlineAuthError (mecanismo REAL de token expirado — verificado live
    2026-08-22; NO usa numbererror).
  • "Sin carriers para la ruta" NO es un numbererror: `cotizarDoble` responde
    `status:"ok"` con `cotizaciones: []` o todas las filas en 999 (verificado
    live) → quote() levanta AveonlineNoCarriersError por 0 opciones.
  • HTTP 5xx → AveonlineTransientError (retry).
  • HTTP 4xx ≠ 429 → AveonlinePermanentError (no retry).
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
import unicodedata
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
# Listado de agentes de despacho (doc oficial
# `integraciones.aveonline.co/docs/nacional/agentes/listadoAgentes`).
AVEONLINE_AGENTES_URL = (
    "https://app.aveonline.co/api/comunes/v1.0/agentes.php"
)
# Registro del "Webhook personalizado" (doc oficial
# `integraciones.aveonline.co/docs/webhookPersonalizadoApi`): upsert por
# empresa (la empresa se identifica del JWT en `Authorization`, SIN prefijo
# Bearer). Aveonline genera `data.token` y lo reenvía en cada notificación.
AVEONLINE_CUSTOM_WEBHOOK_URL = (
    "https://api.aveonline.co/api-integrations/public/api/integrations/custom-webhook"
)

# Timeouts (dossier §15.5: plugin oficial usa CURLOPT_TIMEOUT=0; nosotros
# preferimos 25s — Envia tiene mismo orden de magnitud).
AVEONLINE_TIMEOUT_SECONDS = 25.0

# Buffer JWT refresh (refresh si expira_at < now + 10min).
JWT_REFRESH_BUFFER_SECONDS = 600

# Cache idempotency local cotización (replica plugin oficial 60s).
QUOTE_CACHE_TTL_SECONDS = 60

# Cache in-memory del idagente auto-resuelto (24h — el agente principal de
# una cuenta casi nunca cambia; mismo patrón que usa el otro proyecto del
# founder. La copia persistida en credentials.idagente es la SoT cross-proceso).
IDAGENTE_CACHE_TTL_SECONDS = 24 * 3600


# ─── Helpers de geo (formato Aveonline) ────────────────────────────────────


def _strip_accents(text: str) -> str:
    """Remueve tildes (e.g. 'Bogotá' → 'Bogota')."""
    return "".join(
        c for c in unicodedata.normalize("NFD", str(text or ""))
        if unicodedata.category(c) != "Mn"
    )


def to_aveonline_city_format(city: str, state: str) -> str:
    """Convierte (city, state) → 'CITY(STATE)' uppercase sin tildes.

    Formato canónico Aveonline (dossier §10.3). Ejemplos:
      ('Bogotá', 'Cundinamarca') → 'BOGOTA(CUNDINAMARCA)'
      ('Bogotá D.C.', 'Bogotá D.C.') → 'BOGOTA(CUNDINAMARCA)' (caso especial)
      ('Medellín', 'Antioquia') → 'MEDELLIN(ANTIOQUIA)'

    Retorna string vacío si falta city o state.
    """
    norm_city = _strip_accents(city).upper().strip()
    norm_state = _strip_accents(state).upper().strip()
    # Limpiar "D.C." / "D. C." que Aveonline NO usa.
    norm_city = norm_city.replace(" D.C.", "").replace(" D. C.", "").strip()
    if norm_city == "BOGOTA" and norm_state in (
        "BOGOTA", "BOGOTA D.C.", "BOGOTA DC", "",
    ):
        norm_state = "CUNDINAMARCA"
    if not norm_city or not norm_state:
        return ""
    return f"{norm_city}({norm_state})"


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
    """Una opción de cotización retornada por cotizarDoble.

    Campos extendidos rev. 107 — todo el subset útil del response Aveonline
    §3.6 dossier. Permite que UI muestre logo, breakdown de costos, peso
    volumétrico, COD support, etc.
    """
    rate_id: str                       # codTransportadora
    carrier_name: str                  # nombreTransportadora
    service_level: str                 # tipoEnvio (e.g. "Mensajeria")
    price_cents: int                   # total COP * 100
    eta_days: Optional[int]            # diasentrega
    # Identidad visual.
    logo_url: Optional[str] = None     # logoTransportadora
    logo_url_alt: Optional[str] = None # logoTransportadora2
    # Trayecto.
    route_code: Optional[str] = None   # codigoTrayecto
    route_type: Optional[str] = None   # trayecto (e.g. "nacional")
    # Paquete validado por Aveonline.
    weight_real_kg: Optional[float] = None        # kilos
    weight_volumetric_kg: Optional[float] = None  # pesovolumen
    units: Optional[int] = None                   # unidades
    declared_value_cop: Optional[int] = None      # valoracion
    valuation_percent: Optional[float] = None     # porcentajeValoracion
    # Breakdown costos (todos en cents para coherencia).
    freight_per_kg_cents: Optional[int] = None    # fletexkilo
    freight_per_unit_cents: Optional[int] = None  # fletexunidad
    freight_total_cents: Optional[int] = None     # fletetotal
    handling_cents: Optional[int] = None          # costoManejo
    cod_extras_cents: Optional[int] = None        # valorOtrosRecaudos
    subtotal_cents: Optional[int] = None          # valorTotal (pre-COD)
    # COD support.
    cod_supported: bool = False                   # contraentrega
    # Raw response audit.
    raw: dict = None


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
        # In-memory cache del idagente auto-resuelto (24h).
        self._idagente_cache: Optional[tuple[str, float]] = None

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
        # Doc oficial autenticación (fetch 2026-08-22): password mala devuelve
        # `status:"ok"` + token HUECO con `cuentas: []` (JWT con `aprobados:[]`
        # que falla después en cada endpoint). Detectarlo aquí como auth error
        # en vez de cachear un token inútil.
        if not data.get("cuentas"):
            raise AveonlineAuthError(
                "Aveonline auth OK pero sin cuentas asociadas (password "
                "inválida o cuenta sin servicios) — revisar credenciales del "
                "tenant."
            )

        new_jwt = data["token"]
        # F-doc (Fase 6): la doc oficial de auth Aveonline dice vigencia de 1 HORA y NO
        # documenta `tiempoToken` como extensor server-side (solo lo respaldan plugins de
        # terceros). Cachear 100000s (~27.8h) arriesga usar un JWT ya inválido server-side
        # → AveonlineAuthError al caller. Se capa el TTL CACHEADO a <=3600s: si tiempoToken
        # sí extiende la vigencia, solo refrescamos un poco más seguido (inofensivo); si no
        # (la doc es correcta), evitamos usar un token stale. Confirmar con Aveonline para
        # subir el cap si aplica.
        # Addendum live 2026-08-22 (cuenta demo): el server SÍ honra `tiempoToken` y lo
        # interpreta en HORAS estampándolo en el `exp` del JWT (pedido 3600 → exp = now +
        # 3600h ≈ 150 días). Mantenemos el cap de 1h (doc-conforme, conservador): peor caso
        # refrescamos más seguido; nunca usamos un token que la doc declara vencido.
        cache_ttl = min(int(tiempo_token), 3600)
        new_expires = (
            datetime.now(timezone.utc) + timedelta(seconds=cache_ttl)
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

    # ─── Agentes de despacho (listadoAgentes) + auto-resolución idagente ─────

    async def list_agents(self) -> dict:
        """Lista los agentes (puntos de despacho) de la cuenta Aveonline.

        Endpoint oficial `listarAgentesPorEmpresaAuth` (doc
        `integraciones.aveonline.co/docs/nacional/agentes/listadoAgentes`,
        verificado live 2026-08-22 contra cuenta demo).

        Returns:
            dict {"ok": bool, "agents": [{id, nombre, direccion, idciudad,
            telefono, email, principal: bool}], "raw": ..., "message": str}.
            `principal` tolera los formatos "SI"/"NO" (live) y "S"/"N"
            (ejemplo de la doc).
        """
        jwt = await self._get_valid_jwt()
        creds = await self._load_credentials()
        empresa_id = creds.get("empresa_id")

        body = {
            "tipo": "listarAgentesPorEmpresaAuth",
            "token": jwt,
            "idempresa": empresa_id,
        }
        try:
            async with httpx.AsyncClient(timeout=AVEONLINE_TIMEOUT_SECONDS) as cx:
                resp = await cx.post(AVEONLINE_AGENTES_URL, json=body)
        except httpx.HTTPError as exc:
            return {"ok": False, "agents": [], "raw": {}, "message": str(exc)}

        if resp.status_code >= 500:
            return {
                "ok": False, "agents": [], "raw": {},
                "message": f"HTTP {resp.status_code}",
            }
        try:
            data = resp.json()
        except ValueError:
            return {"ok": False, "agents": [], "raw": {}, "message": "bad json"}

        agents = [
            {
                "id": str(a.get("id") or ""),
                "nombre": str(a.get("nombre") or ""),
                "direccion": str(a.get("direccion") or ""),
                "idciudad": str(a.get("idciudad") or ""),
                "telefono": str(a.get("telefono") or ""),
                "email": str(a.get("email") or ""),
                "principal": str(a.get("principal") or "").strip().upper()
                in ("S", "SI", "Y", "YES", "1", "TRUE"),
            }
            for a in (data.get("agentes") or [])
            if isinstance(a, dict) and a.get("id")
        ]
        return {
            "ok": data.get("status") == "ok",
            "agents": agents,
            "raw": data,
            "message": data.get("message") or "",
        }

    async def _resolve_idagente(self, creds: dict) -> str:
        """Resuelve el `idagente` (dirección de despacho Aveonline) del tenant.

        Precedencia:
          1. `credentials.idagente` — override manual del tenant (lo persiste
             la UI desde `GET /aveonline/agents`).
          2. Cache in-memory 24h (mismo patrón que el otro proyecto del
             founder: listarAgentes → agente principal).
          3. `listarAgentesPorEmpresaAuth` → agente con `principal=SI` (o el
             primero si ninguno es principal). Se persiste best-effort en
             `credentials.idagente` vía RPC `upsert_aveonline_idagente` para
             que los demás procesos (api/orchestrator/worker) lo reusan.
          4. "" — Aveonline auto-calcula el agente de la ciudad origen, pero
             con MENOS carriers (verificado live 2026-08-22: sin idagente la
             cuenta demo pierde INTERRAPIDISIMO en la cotización).

        NUNCA usar `asesorlogistico` como fallback: es el asesor COMERCIAL
        de la cuenta (en la demo vale "0"), no un agente de despacho.
        """
        manual = str(creds.get("idagente") or "").strip()
        if manual:
            return manual

        if self._idagente_cache:
            cached_id, ts = self._idagente_cache
            if time.time() - ts < IDAGENTE_CACHE_TTL_SECONDS:
                return cached_id

        try:
            result = await self.list_agents()
        except Exception as exc:  # noqa: BLE001 — resolución best-effort
            logger.warning(
                "[aveonline.idagente] tenant=%s list_agents err: %s",
                self.tenant_id[:8], exc,
            )
            return ""
        agents = result.get("agents") or []
        if not result.get("ok") or not agents:
            logger.warning(
                "[aveonline.idagente] tenant=%s sin agentes (ok=%s msg=%s)",
                self.tenant_id[:8], result.get("ok"), result.get("message"),
            )
            return ""

        principal = next(
            (a for a in agents if a.get("principal")), agents[0],
        )
        resolved = str(principal.get("id") or "").strip()
        if not resolved:
            return ""

        self._idagente_cache = (resolved, time.time())

        # Persistir best-effort (SoT cross-proceso). El RPC hace merge jsonb
        # atómico — no pisa jwt_token ni otros campos de credentials.
        try:
            self.supabase.rpc(
                "upsert_aveonline_idagente",
                {"p_tenant_id": self.tenant_id, "p_idagente": resolved},
            ).execute()
        except Exception as exc:  # noqa: BLE001 — no romper la cotización
            logger.warning(
                "[aveonline.idagente] tenant=%s persist err (cache local OK): %s",
                self.tenant_id[:8], exc,
            )
            # Cachear igual: el valor resuelto es válido aunque la DB falle.
        else:
            creds["idagente"] = resolved
            self._credentials_cache = creds

        logger.info(
            "[aveonline.idagente] tenant=%s auto-resuelto idagente=%s "
            "(agente=%r principal=%s)",
            self.tenant_id[:8], resolved, principal.get("nombre"),
            principal.get("principal"),
        )
        return resolved

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
            # El recaudo COD cambia la tarifa (valorOtrosRecaudos) → debe
            # ser parte de la llave de cache o dos carts COD con distinto
            # total colisionarían.
            "r": package.get("valorrecaudo", 0),
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
                "valorrecaudo": int COP a recaudar si COD (default 0) — la
                    comisión de recaudo entra al `total` vía
                    `valorOtrosRecaudos` (doc oficial cotización); cotizar
                    COD con valorrecaudo=0 SUB-PRECÍA la guía.
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
        # `idagente` (dirección de despacho) es REQUERIDO según la doc oficial
        # de cotización — sin él Aveonline auto-calcula pero con MENOS carriers
        # (live 2026-08-22: la demo pierde INTERRAPIDISIMO). Auto-resolución:
        # credentials.idagente → listarAgentes (principal, cache 24h).
        idagente = await self._resolve_idagente(creds)
        # Recaudo COD: el courier cobra productos + envío; la comisión de
        # recaudo (`valorOtrosRecaudos`) solo aparece si se envía el monto.
        cod_enabled = bool(package.get("cod_enabled"))
        valorrecaudo = (
            max(0, int(package.get("valorrecaudo") or 0)) if cod_enabled else 0
        )

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
            # Combo de pago (tabla oficial "Formas de pago de la guía"):
            # sin recaudo → contraentrega=0/idasumecosto=0 (remitente paga
            # transporte). Con recaudo → contraentrega=1/idasumecosto=1
            # (destinatario paga recaudo + transporte + servicio recaudo) —
            # espejo del combo que usa generate_guide.
            "idasumecosto": 1 if cod_enabled else 0,
            "contraentrega": 1 if cod_enabled else 0,
            "contraentregaPayment": 0,
            "valorrecaudo": valorrecaudo,
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
            # Caso documentado "cotizaciones no encontradas" (doc oficial
            # cotización): sin cobertura para la ruta → NoCarriers, no
            # permanente genérico (el bot lo traduce a mensaje útil).
            _msg_l = str(data.get("message") or "").lower()
            if "cotizaciones no encontradas" in _msg_l:
                raise AveonlineNoCarriersError(
                    f"Aveonline sin cotizaciones para "
                    f"{origin.get('city')} → {destination.get('city')}."
                )
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
            # Parseo defensivo — Aveonline puede devolver strings donde
            # esperamos números (dossier §3.6 nota).
            def _to_int_cents_or_none(v):
                try:
                    return int(float(v) * 100) if v not in (None, "", "000") else None
                except (TypeError, ValueError):
                    return None

            def _to_float_or_none(v):
                try:
                    return float(v) if v not in (None, "", "000") else None
                except (TypeError, ValueError):
                    return None

            def _to_int_or_none(v):
                try:
                    return int(float(v)) if v not in (None, "", "000") else None
                except (TypeError, ValueError):
                    return None

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
                # Identidad visual.
                logo_url=row.get("logoTransportadora") or None,
                logo_url_alt=row.get("logoTransportadora2") or None,
                # Trayecto.
                route_code=str(row.get("codigoTrayecto") or "") or None,
                route_type=str(row.get("trayecto") or "") or None,
                # Paquete.
                weight_real_kg=_to_float_or_none(row.get("kilos")),
                weight_volumetric_kg=_to_float_or_none(row.get("pesovolumen")),
                units=_to_int_or_none(row.get("unidades")),
                declared_value_cop=_to_int_or_none(row.get("valoracion")),
                valuation_percent=_to_float_or_none(row.get("porcentajeValoracion")),
                # Breakdown costos (multiplico por 100 porque vienen en COP enteros).
                freight_per_kg_cents=_to_int_cents_or_none(row.get("fletexkilo")),
                freight_per_unit_cents=_to_int_cents_or_none(row.get("fletexunidad")),
                freight_total_cents=_to_int_cents_or_none(row.get("fletetotal")),
                handling_cents=_to_int_cents_or_none(row.get("costoManejo")),
                cod_extras_cents=_to_int_cents_or_none(row.get("valorOtrosRecaudos")),
                subtotal_cents=_to_int_cents_or_none(row.get("valorTotal")),
                # COD.
                cod_supported=bool(row.get("contraentrega", False)),
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
        """Mapea numbererror → excepción tipada.

        Tabla OFICIAL vigente (fetch 2026-08-22 de
        `integraciones.aveonline.co/docs/nacional/cotizacion/` — misma tabla
        en dossier §14.2). OJO con dos correcciones al mapeo histórico:
          • -1/-2 NO son "genérico"/"credenciales": son origen/destino
            inexistente → error PERMANENTE de dato (retry inútil).
          • -3 NO es "sin carriers": es peso ≤ 0. El caso "sin carriers" en
            `cotizarDoble` llega como `cotizaciones: []` o filas 999
            (verificado live 2026-08-22) → AveonlineNoCarriersError por 0
            opciones en quote(), no por este mapeo.
        El token expirado NO usa numbererror: llega como message
        "credenciales incorrectas" / "autenticacion fallida" (doc oficial +
        live 2026-08-22) → se detecta por mensaje → AveonlineAuthError.
        """
        msg = message or f"Aveonline numbererror={code}"
        # Detección de auth por MENSAJE (mecanismo real documentado).
        msg_l = msg.lower()
        if "credenciales incorrectas" in msg_l or "autenticacion fallida" in msg_l:
            raise AveonlineAuthError(msg)

        c = str(code or "").strip().lstrip("+")
        # Datos inválidos del request (origen/destino/peso/unidades/valor
        # declarado): permanentes — reintentar no cambia el resultado. -5 está
        # pre-corregido client-side (floor 10k); si llega, es bug del caller.
        if c in ("-1", "-2", "-3", "-4", "-5"):
            raise AveonlinePermanentError(msg)
        # Límites del paquete para el carrier/ruta (-6 unidades, -7 kilos,
        # -1000 trayecto con límites — su mensaje trae kilosMaximos /
        # unidadesMaximas). El cliente debe dividir el envío.
        if c in ("-6", "-7", "-1000"):
            raise AveonlinePackageLimitError(msg)
        if c in ("999", "-999"):
            # Servicio no configurado / trayecto inválido. Con cotizarDoble
            # llega POR FILA (se filtra en quote); global = bug `cotizar2`
            # (dossier §0.1) o cuenta sin setup.
            raise AveonlinePermanentError(msg)
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

    # ─── Generación de guía nacional (Rev. 107) ─────────────────────────────

    async def generate_guide(
        self,
        *,
        origin: dict,
        destination: dict,
        package: dict,
        carrier: dict,
        sender: dict,
        recipient: dict,
        simulate: bool = True,
    ) -> dict:
        """Genera guía nacional vía `tipo=generarGuia2`.

        Doc dossier sec 4 (verbatim del plugin WooCommerce + doc oficial).

        Args:
            origin: {"dane": str, "city": str}
            destination: {"dane": str, "city": str}
            package: {weight_kg, length_cm, width_cm, height_cm,
                      declared_value_cop, units, content}
            carrier: {"idtransportador": str, "service_level": str}
                Identificador transportadora (codTransportadora del quote).
            sender: {"nit", "nombre", "direccion", "barrio", "telefono",
                     "celular", "email"}
            recipient: {"doc", "nombre", "direccion", "barrio", "telefono",
                        "celular", "email"}
            simulate: True → `bloquegenerarguia="0"` (NO factura, retorna
                guía dummy). False → genera guía REAL facturable.

        Returns:
            dict canónico:
              {
                "ok": True,
                "tracking_number": str,
                "label_url": str,
                "tracking_url": str,
                "raw": <full response>,
              }
            o {"ok": False, "error": str, "code": str}.

        Raises:
            AveonlineAuthError, AveonlineTransientError,
            AveonlinePermanentError.

        Rev. 107: implementación inicial con simulate=True por default —
        modo seguro. Tenant cambia a simulate=False cuando esté listo
        para guías reales. Idempotency NO implementada en este endpoint
        Aveonline (dossier confirma) — caller debe deduplicar a nivel
        DB (constraint UNIQUE order_id en shipments).
        """
        jwt = await self._get_valid_jwt()
        creds = await self._load_credentials()
        empresa_id = creds.get("empresa_id")
        # Auto-resolución idagente (misma regla que quote): credentials →
        # listarAgentes principal (cache 24h). Sin él la guía puede salir con
        # el agente equivocado o ser rechazada por carriers con código de
        # agente (INTERRAPIDISIMO).
        idagente = await self._resolve_idagente(creds)

        declared = max(10000, int(package.get("declared_value_cop") or 10000))
        weight_kg = float(package.get("weight_kg") or 0.5)
        units = int(package.get("units") or 1)

        producto_item = {
            "alto": int(package.get("height_cm") or 5),
            "largo": int(package.get("length_cm") or 15),
            "ancho": int(package.get("width_cm") or 10),
            "peso": weight_kg,
            "unidades": units,
            "nombre": str(package.get("content") or "Pedido"),
            "valorDeclarado": declared,
        }

        body = {
            "tipo": "generarGuia2",
            "token": jwt,
            "idempresa": empresa_id,
            "codigo": "",  # password resuelto via vault, no necesario aquí
            "dsclavex": "",
            "plugin": "konvi-saas",
            "origen": str(origin.get("dane") or origin.get("city") or ""),
            "dsdirre": str(sender.get("direccion") or ""),
            "dsbarrioo": str(sender.get("barrio") or ""),
            "dsnitre": str(sender.get("nit") or ""),
            "dstelre": str(sender.get("telefono") or ""),
            "dscelularre": str(sender.get("celular") or ""),
            "dscorreopre": str(sender.get("email") or ""),
            "dsnombre": str(sender.get("nombre") or ""),
            "destino": str(destination.get("dane") or destination.get("city") or ""),
            "IdTipoEntrega": "1",  # 1=domicilio (default), 2=oficina
            "dsdir": str(recipient.get("direccion") or ""),
            "dsbarrio": str(recipient.get("barrio") or ""),
            "dsnit": str(recipient.get("doc") or ""),
            "dsnombrecompleto": str(recipient.get("nombre") or ""),
            "dscorreop": str(recipient.get("email") or ""),
            "dstel": str(recipient.get("telefono") or ""),
            "dscelular": str(recipient.get("celular") or ""),
            "idtransportador": str(carrier.get("idtransportador") or ""),
            "idagente": idagente,
            "unidades": units,
            "productos": [producto_item],
            "dscontenido": str(package.get("content") or "Pedido"),
            "dscom": "",
            # Rev. 108 Fase B — COD: tomar valorrecaudo + contraentrega del
            # package si están definidos. Si NO COD, ambos quedan en 0
            # (igual que credit Wompi flow).
            "valorrecaudo": int(package.get("valorrecaudo") or 0),
            "contraentrega": 1 if package.get("cod_enabled") else 0,
            "idasumecosto": 1,  # tenant asume costo
            "bloquegenerarguia": "0" if simulate else "1",
            "relacion_envios": "1",
            "enviarcorreos": "1",  # Aveonline notifica al destinatario
            "cartaporte": "0",
            # UAT founder 2026-07-10: valorMinimo=1 forzaba la valoración MÍNIMA de la
            # cuenta ($10.000) pisando el valorDeclarado real (guía impresa con seguro de
            # 10k para mercancía de $109.650) e inconsistente con el quote (valorMinimo=0
            # en cotizarDoble). 0 = respetar el valorDeclarado enviado (dossier §3.5).
            "valorMinimo": 0,
            "numeroFactura": "",
            "numeroBolsa": "",
            "dsfecha_vencimiento": "",
            "dsfecha_cita": "",
            "dscodigo_cita": "",
            "dsvalor_pedido": str(declared),
            "envioGratis": 0,
        }

        # Rev. 108 audit — log request body completo (sin JWT) para debug.
        body_log = {k: v for k, v in body.items() if k != "token"}
        logger.info(
            "[AVEONLINE_GEN_GUIDE] request tenant=%s carrier=%s dest=%s "
            "weight=%s cod=%s recaudo=%s body=%s",
            self.tenant_id[:8],
            body.get("idtransportador"),
            body.get("destino"),
            weight_kg,
            body.get("contraentrega"),
            body.get("valorrecaudo"),
            json.dumps(body_log, ensure_ascii=False)[:2000],
        )

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(AVEONLINE_NAL_URL, json=body)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            raise AveonlineTransientError(f"generate_guide HTTP error: {exc}")
        except Exception as exc:
            raise AveonlinePermanentError(f"generate_guide error: {exc}")

        # Audit response RAW completo.
        logger.info(
            "[AVEONLINE_GEN_GUIDE] response tenant=%s status=%s msg=%s "
            "raw=%s",
            self.tenant_id[:8],
            data.get("status"),
            data.get("message", "")[:200],
            json.dumps(data, ensure_ascii=False)[:1500],
        )

        # Schema response (dossier sec 4.3):
        #   {status: "ok"|"error", message, resultado: {guia: {codigo, mensaje,
        #     numguia, rutaguia, rotulo, rutasticker, transportadora, ...}}}
        if data.get("status") != "ok":
            return {
                "ok": False,
                "error": data.get("message") or "generate_guide failed",
                "code": "AVEONLINE_GUIDE_ERROR",
                "raw": data,
            }

        guia = (data.get("resultado") or {}).get("guia") or {}
        if guia.get("codigo") and str(guia["codigo"]) != "0":
            return {
                "ok": False,
                "error": guia.get("mensaje") or "guia code error",
                "code": f"AVEONLINE_GUIDE_CODE_{guia.get('codigo')}",
                "raw": data,
            }

        return {
            "ok": True,
            "tracking_number": str(guia.get("numguia") or ""),
            "label_url": str(guia.get("rutasticker") or guia.get("rutaguia") or ""),
            "tracking_url": str(guia.get("rutaguia") or guia.get("rutasticker") or ""),
            "carrier_name": str(guia.get("transportadora") or ""),
            "simulated": simulate is True,
            "raw": data,
        }

    # ─── Cancel guía (Rev. 109 — Ley 1480 cancelación) ───────────────────
    # F-doc (Fase 6): `cancelarGuia` NO está en la documentación oficial de Aveonline
    # (integraciones.aveonline.co) — solo lo usan plugins de terceros (WooCommerce). El
    # POST real va a AVEONLINE_NAL_URL (app.aveonline.co/api/nal/.../generarGuiaTransporteNacional.php),
    # NO a webservices.aveonline.co como decía el comentario anterior. La ÚNICA primitiva
    # de cancelación documentada es `eliminarRelacionEnvios` (v2.0), que opera sobre una
    # RELACIÓN de envíos (batch), no sobre una guía individual ya generada — el dossier
    # §8.2 confirma que NO existe endpoint público para anular una guía individual.
    #
    # Por eso este método es best-effort: si Aveonline retorna no-'exitoso' devuelve
    # ok=False y el caller ESCALA A OPERADOR para coordinar manual con el courier (el
    # fallback correcto dado que la cancelación individual no está oficialmente soportada).
    # Solo tiene chance de funcionar si la guía aún NO fue recogida ('labeled').
    # TODO (verificar con Aveonline): reimplementar sobre eliminarRelacionEnvios si el
    # flujo real usa relaciones, o formalizar la escalación a operador como el camino único.

    async def cancel_guide(self, *, tracking_number: str) -> dict:
        """Solicita cancelación de una guía Aveonline.

        Args:
            tracking_number: numguia retornado por generate_guide.

        Returns:
            dict {
              "ok": True | False,
              "tracking_number": str,
              "message": str,        # texto del response Aveonline
              "raw": <full response>,
            }

        Errores:
            • AveonlineAuthError → JWT inválido / expirado.
            • AveonlineTransientError → 5xx / timeout (retry).
            • AveonlinePermanentError → 4xx (guía ya recogida, no existe, etc).

        UX: si retorna ok=False, caller debe escalar al operador para
        coordinar manual con el courier (llamada/notificación).
        """
        if not tracking_number or not str(tracking_number).strip():
            return {
                "ok": False,
                "error": "tracking_number vacío",
                "code": "MISSING_TRACKING",
            }

        jwt = await self._get_valid_jwt()
        creds = await self._load_credentials()
        empresa_id = creds.get("empresa_id")

        body = {
            "tipo": "cancelarGuia",
            "token": jwt,
            "idempresa": empresa_id,
            "numguia": str(tracking_number).strip(),
            "plugin": "konvi-saas",
        }

        logger.info(
            "[AVEONLINE_CANCEL_GUIDE] tenant=%s tracking=%s",
            self.tenant_id[:8], tracking_number,
        )
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(AVEONLINE_NAL_URL, json=body)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            raise AveonlineTransientError(f"cancel_guide HTTP error: {exc}")
        except Exception as exc:
            raise AveonlinePermanentError(f"cancel_guide error: {exc}")

        # Audit response RAW.
        logger.info(
            "[AVEONLINE_CANCEL_GUIDE] response tenant=%s tracking=%s data=%s",
            self.tenant_id[:8], tracking_number,
            json.dumps(data, ensure_ascii=False)[:1000],
        )

        # Aveonline cancelarGuia response shape esperada:
        #   {"resultado": "exitoso"|"error", "mensaje": str, ...}
        result = (data or {}).get("resultado", "").lower()
        message = (data or {}).get("mensaje", "")
        ok = result == "exitoso" or "cancelad" in message.lower()

        return {
            "ok": ok,
            "tracking_number": str(tracking_number),
            "message": message,
            "raw": data,
        }

    # ─── Webhook management (Rev. 108) ─────────────────────────────────────
    # DOS mecanismos de registro coexisten:
    #
    #  A) OFICIAL vigente — `register_custom_webhook` (doc
    #     `integraciones.aveonline.co/docs/webhookPersonalizadoApi`, verificado
    #     2026-08-22): POST api-integrations/.../custom-webhook con el JWT en
    #     `Authorization` (SIN Bearer). UPSERT por empresa (una sola URL de
    #     tracking por cuenta — addendum dossier 2026-08-16). Aveonline genera
    #     `data.token` y lo reenvía TOP-LEVEL en cada notificación → ese token
    #     es el secret que persiste Konvi (bcrypt) para verificar eventos.
    #
    #  B) LEGACY AveCRM — `create_webhook` (avestock/api/createWebhook.php):
    #     hasta 4 pares param1..param4 que viajan en cada POST. Usamos
    #     `param1_name="secret"` + `param1_value=<UUID>` como pseudo-HMAC
    #     (dossier §6.2). NO es HMAC criptográfico — el secret va en plaintext
    #     en el body — pero un atacante necesita la URL+secret para spoofear.
    #     Rotación trimestral vía `tenant_webhook_secrets` mitiga exposición.
    #
    # El receiver (`routers/aveonline_webhook.py`) acepta AMBOS formatos.
    # Referencias: /docs/webhookPersonalizadoApi + /docs/avecrm/crearWebhook/

    async def register_custom_webhook(self, *, name: str, webhook_url: str) -> dict:
        """Registra (o actualiza) el Webhook personalizado — endpoint OFICIAL.

        Doc `webhookPersonalizadoApi`: la operación es IDEMPOTENTE por empresa
        (si ya existe webhook, se actualiza con los datos enviados). La empresa
        se identifica del JWT — no va en el payload.

        Args:
            name: nombre visible de la integración (panel "Mis integraciones").
            webhook_url: URL pública que recibirá la trama de estados.

        Returns:
            dict {"ok": bool, "token": str|None, "raw": <response>,
                  "message": str, "updated": bool}.
            `token` es el que Aveonline reenvía en cada POST (data.token) —
            persistir su hash como secret de verificación. `updated=True` si
            Aveonline actualizó uno existente (HTTP 200) vs creado (201).

        Raises:
            AveonlineAuthError: JWT ausente/inválido (403 documentado).
            AveonlinePermanentError: payload inválido (422 documentado) u
                otro 4xx.
            AveonlineTransientError: red/5xx.
        """
        jwt = await self._get_valid_jwt()
        body = {"name": name[:120], "webhookUrl": webhook_url[:500]}
        try:
            async with httpx.AsyncClient(timeout=AVEONLINE_TIMEOUT_SECONDS) as client:
                resp = await client.post(
                    AVEONLINE_CUSTOM_WEBHOOK_URL,
                    json=body,
                    # Doc: "se envía en el header Authorization sin el prefijo
                    # Bearer" (misma convención que tiposEstadosEnvios).
                    headers={"Authorization": jwt},
                )
        except httpx.HTTPError as exc:
            raise AveonlineTransientError(f"custom-webhook network: {exc}") from exc

        try:
            data = resp.json()
        except ValueError:
            data = {}

        if resp.status_code in (401, 403):
            raise AveonlineAuthError(
                f"custom-webhook auth HTTP {resp.status_code}: "
                f"{data.get('error') or resp.text[:200]}"
            )
        if resp.status_code == 422:
            raise AveonlinePermanentError(
                f"custom-webhook payload inválido: {str(data)[:300]}"
            )
        if resp.status_code >= 500:
            raise AveonlineTransientError(
                f"custom-webhook HTTP {resp.status_code}"
            )
        if resp.status_code not in (200, 201):
            raise AveonlinePermanentError(
                f"custom-webhook HTTP {resp.status_code}: {resp.text[:200]}"
            )

        token = ((data.get("data") or {}).get("token") or "") or None
        return {
            "ok": bool(data.get("success", True)),
            "token": token,
            "raw": data,
            "message": data.get("message") or "",
            "updated": resp.status_code == 200,
        }

    async def create_webhook(
        self, *, url: str, secret: str,
        extra_params: Optional[dict] = None,
    ) -> dict:
        """Registra un webhook en Aveonline para esta cuenta tenant (LEGACY AveCRM).

        Preferir `register_custom_webhook` (endpoint oficial vigente, upsert
        por empresa). Este queda como fallback para cuentas donde el endpoint
        oficial falle.

        Args:
            url: URL pública donde Aveonline hará POST con estados de guía.
                Máximo 500 chars. DEBE incluir el path completo, ej.
                `https://api.konvi.app/api/v1/webhooks/aveonline/{tenant_id}`.
            secret: secret plaintext que Aveonline enviará en cada POST como
                `param1_value`. Generado con `secrets.token_urlsafe(32)`,
                bcrypt hash persistido en `tenant_webhook_secrets`. Aveonline
                lo guarda plaintext en su lado.
            extra_params: opcional dict de hasta 3 pares adicionales
                (param2..param4).

        Returns:
            dict {"ok": bool, "raw": <full response>, "message": str}.

        Notas implementación:
            - Endpoint `app.aveonline.co/avestock/api/createWebhook.php`.
            - Body: tipo='authave', empresa=<id>, url, param1_name='secret',
              param1_value=<secret>.
            - Si ya existe webhook con misma URL → response error
              "Ya existe un webhook con la misma url". Caller debe primero
              llamar `delete_webhook` y luego re-crear (idempotent rotate).
        """
        creds = await self._load_credentials()
        empresa_id = creds.get("empresa_id")
        if not empresa_id:
            raise AveonlinePermanentError(
                "Aveonline empresa_id ausente en credentials — no se puede "
                "registrar webhook."
            )

        body: dict[str, Any] = {
            "tipo": "authave",
            "empresa": int(empresa_id) if str(empresa_id).isdigit() else empresa_id,
            "url": url[:500],
            "param1_name": "secret",
            "param1_value": secret[:255],
        }
        # Permitir extra metadata (ej. tenant_id, ambiente) en param2..param4
        # útil para debugging webhooks en logs Aveonline.
        if extra_params:
            for idx, (k, v) in enumerate(list(extra_params.items())[:3], start=2):
                body[f"param{idx}_name"] = str(k)[:50]
                body[f"param{idx}_value"] = str(v)[:255]

        endpoint = "https://app.aveonline.co/avestock/api/createWebhook.php"
        try:
            async with httpx.AsyncClient(timeout=AVEONLINE_TIMEOUT_SECONDS) as client:
                resp = await client.post(endpoint, json=body)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as exc:
            raise AveonlinePermanentError(
                f"create_webhook HTTP {exc.response.status_code}: {exc.response.text[:200]}"
            )
        except httpx.HTTPError as exc:
            raise AveonlineTransientError(f"create_webhook network: {exc}")
        except Exception as exc:
            raise AveonlinePermanentError(f"create_webhook unexpected: {exc}")

        # Shape variants:
        #   Success: {success: true, messages: "Creado exitosamente"}
        #   Conflict: {success: false, messages: "...Ya existe..."}
        #   AuthFail: {status: "error", message: "Credenciales invalidas..."}
        ok = bool(data.get("success"))
        msg = data.get("messages") or data.get("message") or ""
        return {"ok": ok, "raw": data, "message": str(msg)}

    async def list_webhooks(self) -> dict:
        """Lista los webhooks registrados para esta empresa.

        Endpoint `listWebhook.php` (mismo patrón que createWebhook).
        Útil para detectar duplicados antes de rotar.

        Returns:
            dict {"ok": bool, "raw": <full response>, "items": list}.
        """
        creds = await self._load_credentials()
        empresa_id = creds.get("empresa_id")
        body = {
            "tipo": "authave",
            "empresa": int(empresa_id) if str(empresa_id).isdigit() else empresa_id,
        }
        endpoint = "https://app.aveonline.co/avestock/api/listWebhook.php"
        try:
            async with httpx.AsyncClient(timeout=AVEONLINE_TIMEOUT_SECONDS) as client:
                resp = await client.post(endpoint, json=body)
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            logger.warning("[AVEONLINE] list_webhooks error: %s", exc)
            return {"ok": False, "raw": {}, "items": [], "message": str(exc)}

        items = []
        if isinstance(data.get("webhooks"), list):
            items = data["webhooks"]
        elif isinstance(data.get("data"), list):
            items = data["data"]
        return {
            "ok": bool(data.get("success", True)),
            "raw": data,
            "items": items,
            "message": data.get("messages") or data.get("message") or "",
        }

    async def delete_webhook(self, *, url: str) -> dict:
        """Elimina un webhook registrado por URL.

        Args:
            url: URL exacta del webhook a eliminar.

        Returns:
            dict {"ok": bool, "raw": <full response>, "message": str}.
        """
        creds = await self._load_credentials()
        empresa_id = creds.get("empresa_id")
        body = {
            "tipo": "authave",
            "empresa": int(empresa_id) if str(empresa_id).isdigit() else empresa_id,
            "url": url,
        }
        endpoint = "https://app.aveonline.co/avestock/api/deleteWebhook.php"
        try:
            async with httpx.AsyncClient(timeout=AVEONLINE_TIMEOUT_SECONDS) as client:
                resp = await client.post(endpoint, json=body)
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            return {"ok": False, "raw": {}, "message": str(exc)}
        ok = bool(data.get("success"))
        return {
            "ok": ok,
            "raw": data,
            "message": data.get("messages") or data.get("message") or "",
        }

    async def list_carriers(self) -> dict:
        """Lista las transportadoras habilitadas para esta cuenta empresa.

        Endpoint: `app.aveonline.co/api/box/v1.0/transportadora.php`
        Body: tipo='listarTransportadorasPorEmpresa', token=<jwt>, id=<empresa>.

        Dossier §3.8 — verificado contra cuenta real 2026-05-21
        (`crittan01@gmail.com` retornó: 99MINUTOS, COORDINADORA MERCANTIL,
        ENVIA, GO ENVIOS, SERVIENTREGA, TCC SA).

        Returns:
            dict {"ok": bool, "items": [{id, text, imagen, imagen2}],
                  "raw": <response>, "message": str}.
        """
        jwt = await self._get_valid_jwt()
        creds = await self._load_credentials()
        empresa_id = creds.get("empresa_id")

        body = {
            "tipo": "listarTransportadorasPorEmpresa",
            "token": jwt,
            "id": empresa_id,
        }
        endpoint = "https://app.aveonline.co/api/box/v1.0/transportadora.php"
        try:
            async with httpx.AsyncClient(timeout=AVEONLINE_TIMEOUT_SECONDS) as client:
                resp = await client.post(endpoint, json=body)
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            return {"ok": False, "items": [], "raw": {}, "message": str(exc)}

        ok = data.get("status") == "ok"
        items_raw = data.get("transportadoras") or []
        items = [
            {
                "id": str(it.get("id") or ""),
                "text": str(it.get("text") or "").strip(),
                "imagen": str(it.get("imagen") or ""),
                "imagen2": str(it.get("imagen2") or ""),
            }
            for it in items_raw if it.get("id")
        ]
        return {
            "ok": ok,
            "items": items,
            "raw": data,
            "message": data.get("message") or "",
        }

    async def get_estado(self, *, tracking_number: str) -> dict:
        """Polling de estado de guía via `obtenerEstadoAuth` (dossier §6.1).

        Endpoint: `app.aveonline.co/api/nal/v1.0/guia.php`.
        Body: tipo='obtenerEstadoAuth', token=<jwt>, id=<empresa>, guia=<num>.

        Útil como respaldo del webhook cuando éste falla o se retrasa.

        Returns:
            dict {"ok": bool, "guias": list[dict], "raw": <response>}.
            Cada item en guias tiene: estado, rutadigitalizada,
            historicos[{estado, fechamostrar, descripcion}].
        """
        jwt = await self._get_valid_jwt()
        creds = await self._load_credentials()
        empresa_id = creds.get("empresa_id")

        body = {
            "tipo": "obtenerEstadoAuth",
            "token": jwt,
            "id": empresa_id,
            "guia": tracking_number,
        }
        endpoint = "https://app.aveonline.co/api/nal/v1.0/guia.php"
        try:
            async with httpx.AsyncClient(timeout=AVEONLINE_TIMEOUT_SECONDS) as client:
                resp = await client.post(endpoint, json=body)
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            return {"ok": False, "guias": [], "raw": {}, "message": str(exc)}

        ok = data.get("status") == "ok"
        return {
            "ok": ok,
            "guias": data.get("guias") or [],
            "raw": data,
            "message": data.get("message") or "",
        }
