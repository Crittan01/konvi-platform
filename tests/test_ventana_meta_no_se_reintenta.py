"""Un mensaje que Meta rechazó por ventana cerrada no se reintenta.

QUÉ ESTABA MAL
`send_whatsapp_message` devuelve `None` para TODO: un timeout, un token inválido, y el
rechazo de Meta por ventana de servicio cerrada (131047). El consumidor de la cola no podía
distinguirlos, así que reintentaba hasta agotar intentos y terminaba marcando el mensaje
con `outbound_send_failed_max_attempts` — un motivo que no le dice nada al operador.

La ventana de 24h no se reabre sola. Cada reintento es una llamada a la Graph API que ya se
sabe que va a fallar.

QUÉ **NO** ESTABA MAL, pese a lo que decía el reporte de readiness
Las notificaciones post-despacho (guía, en ruta, entregado, novedad, reembolso) salen
TAMBIÉN por correo desde el webhook de Aveonline, con plantilla propia cada una, y el
correo es obligatorio para crear cualquier pedido. El comprador SÍ se entera. Esto arregla
la mitad de WhatsApp; no es un apagón de la notificación.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "services" / "ai-orchestrator"))

import whatsapp_sender as ws  # noqa: E402


class _Resp:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body
        self.text = str(body)

    def json(self):
        return self._body


def _limpiar():
    ws._ULTIMO_ERROR.clear()


# ─── El código de Meta deja de perderse ─────────────────────────────────────

def test_el_rechazo_por_ventana_se_reconoce():
    _limpiar()
    ws._ULTIMO_ERROR[ws._clave_error("t1", "573001112233")] = ws.META_ERROR_FUERA_DE_VENTANA
    assert ws.fuera_de_ventana("t1", "573001112233")


def test_otro_error_de_meta_NO_es_ventana_cerrada():
    """Un token vencido o un número inválido sí ameritan reintento; confundirlos con la
    ventana los daría por perdidos en el primer intento."""
    _limpiar()
    ws._ULTIMO_ERROR[ws._clave_error("t1", "573001112233")] = 190      # token
    assert not ws.fuera_de_ventana("t1", "573001112233")


def test_un_timeout_no_marca_ventana_cerrada():
    """Un timeout no trae código: se registra como None y se reintenta."""
    _limpiar()
    ws._ULTIMO_ERROR[ws._clave_error("t1", "573001112233")] = None
    assert not ws.fuera_de_ventana("t1", "573001112233")


def test_sin_intento_previo_no_se_asume_nada():
    _limpiar()
    assert not ws.fuera_de_ventana("t1", "573009999999")


def test_el_telefono_se_normaliza_igual_al_escribir_y_al_leer():
    """Si la clave se calculara distinto en cada lado, `fuera_de_ventana` consultaría una
    entrada que nunca se escribió — la guarda sería letra muerta."""
    _limpiar()
    ws._ULTIMO_ERROR[ws._clave_error("t1", "+57 300-111 2233")] = ws.META_ERROR_FUERA_DE_VENTANA
    assert ws.fuera_de_ventana("t1", "573001112233")
    assert ws.fuera_de_ventana("t1", "+573001112233")


def test_el_codigo_se_extrae_del_cuerpo_de_la_graph_api():
    assert ws._codigo_de_error(_Resp(400, {"error": {"code": 131047}})) == 131047
    assert ws._codigo_de_error(_Resp(400, {"error": {"code": "131047"}})) == 131047


def test_un_cuerpo_raro_no_revienta_el_envio():
    """Meta puede responder con HTML de un proxy. Que el parseo falle no puede tumbar el
    consumidor de la cola."""
    for cuerpo in ({}, {"error": {}}, {"error": {"code": "no-es-un-numero"}}, "texto plano"):
        assert ws._codigo_de_error(_Resp(500, cuerpo)) is None


def test_un_envio_exitoso_borra_el_error_viejo():
    """Si no se limpiara, un rechazo de ayer marcaría como fuera de ventana un envío que
    hoy sí salió."""
    fuente = (REPO_ROOT / "services" / "ai-orchestrator" / "whatsapp_sender.py").read_text()
    i = fuente.index('return message_id')
    assert "_ULTIMO_ERROR.pop" in fuente[i - 400:i]


# ─── El consumidor deja de reintentar ───────────────────────────────────────

def test_el_consumidor_corta_en_vez_de_agotar_intentos():
    fuente = (REPO_ROOT / "services" / "ai-orchestrator" / "worker.py").read_text()
    i_ventana = fuente.index("_fuera_de_ventana(tenant_id, to_phone)")
    i_max = fuente.index("if read_ct >= max(1, WHATSAPP_OUTBOUND_MAX_ATTEMPTS):")
    assert i_ventana < i_max, "la guarda debe evaluarse ANTES del contador de intentos"
    bloque = fuente[i_ventana:i_max]
    assert '"fuera_de_ventana_csw"' in bloque, "el motivo tiene que ser específico"
    assert "_ack_whatsapp_outbound_message" in bloque, "hay que sacarlo de la cola"


def test_el_motivo_distingue_la_ventana_del_fallo_de_red():
    """`outbound_send_failed_max_attempts` no le dice nada al operador. Que la ventana esté
    cerrada no es un fallo del sistema: es el cliente que lleva más de 24h sin escribir."""
    fuente = (REPO_ROOT / "services" / "ai-orchestrator" / "worker.py").read_text()
    assert "fuera_de_ventana_csw" in fuente
    assert "outbound_send_failed_max_attempts" in fuente   # sigue existiendo para lo demás


def test_se_cuenta_aparte_de_los_fallos_reales():
    fuente = (REPO_ROOT / "services" / "ai-orchestrator" / "worker.py").read_text()
    assert '"wa_outbound_out_of_window": 0,' in fuente


# ─── Lo que este arreglo NO es ──────────────────────────────────────────────

def test_las_notificaciones_post_despacho_tambien_salen_por_correo():
    """Guardián contra la conclusión equivocada: esto NO es "el cliente nunca se entera".
    Cada evento de envío tiene su plantilla de correo y se dispara junto al WhatsApp desde
    el webhook de Aveonline."""
    wh = (REPO_ROOT / "services" / "api" / "routers" / "aveonline_webhook.py").read_text()
    for modo in ("shipment_in_transit", "shipment_delivered", "shipment_exception"):
        assert f'template_mode="{modo}"' in wh, modo

    wompi = (REPO_ROOT / "services" / "api" / "routers" / "wompi_webhook.py").read_text()
    for composer in (
        "_compose_shipment_label_ready_email_html",
        "_compose_shipment_in_transit_email_html",
        "_compose_shipment_delivered_email_html",
        "_compose_shipment_exception_email_html",
        "_compose_refund_completed_email_html",
    ):
        assert f"def {composer}" in wompi, composer


def test_y_el_correo_es_obligatorio_para_crear_un_pedido():
    """Por eso el canal de correo alcanza a TODOS los compradores, no solo a los que
    dieron correo por su cuenta."""
    fuente = (REPO_ROOT / "services" / "ai-orchestrator" / "agentic" / "legacy_adapters"
              / "payment.py").read_text()
    i = fuente.index("missing = [")
    assert '"email"' in fuente[i:i + 300]
