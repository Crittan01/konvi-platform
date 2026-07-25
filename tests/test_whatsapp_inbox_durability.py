"""Durabilidad del inbound de WhatsApp — el mensaje no se pierde si el proceso muere.

El bug que esto cierra: `receive_message` responde 200 a Meta ANTES de persistir (política
obligatoria de Meta) y delega a una tarea in-process. Como Meta no reintenta ante un 200, si el
proceso moría en ese hueco el mensaje del cliente se perdía PARA SIEMPRE, con un `logger.error`
como único rastro.

Lo que se prueba acá es la propiedad, no la implementación: tras el ACK, el payload está en el
inbox; si el procesamiento falla, la fila queda PENDIENTE (recuperable) en vez de desaparecer.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

CONNECTOR = Path(__file__).resolve().parents[1] / "services" / "connector-whatsapp"
if str(CONNECTOR) not in sys.path:
    sys.path.insert(0, str(CONNECTOR))


@pytest.fixture
def inbox_mod():
    import services.inbox as mod
    for k in mod._metrics:
        mod._metrics[k] = 0
    return mod


def test_persist_inbox_guarda_el_payload_crudo(inbox_mod):
    """El payload debe quedar durable ANTES de que se le responda 200 a Meta."""
    sb = MagicMock()
    with patch.object(inbox_mod, "_client", return_value=sb):
        inbox_mod.persist_inbox("sha-abc", "tenant-1", {"entry": [{"id": "x"}]})
    args = sb.table.return_value.insert.call_args[0][0]
    assert args["body_sha256"] == "sha-abc"
    assert args["tenant_id"] == "tenant-1"
    assert args["raw_payload"] == {"entry": [{"id": "x"}]}
    assert inbox_mod._metrics["inbox_persisted"] == 1


def test_reintento_de_meta_con_el_mismo_body_no_duplica(inbox_mod):
    """Meta reintenta ante un no-200. El mismo body → misma PK → se ignora el 23505."""
    sb = MagicMock()
    sb.table.return_value.insert.return_value.execute.side_effect = Exception(
        'duplicate key value violates unique constraint (23505)'
    )
    with patch.object(inbox_mod, "_client", return_value=sb):
        inbox_mod.persist_inbox("sha-dup", "tenant-1", {})  # no debe lanzar


def test_error_real_de_persistencia_se_propaga(inbox_mod):
    """Un fallo que NO es duplicado no debe enmascararse: el caller lo degrada a best-effort,
    pero el módulo no lo esconde."""
    sb = MagicMock()
    sb.table.return_value.insert.return_value.execute.side_effect = Exception("conexión caída")
    with patch.object(inbox_mod, "_client", return_value=sb):
        with pytest.raises(Exception, match="conexión caída"):
            inbox_mod.persist_inbox("sha-err", "tenant-1", {})


def test_procesamiento_ok_marca_la_fila(inbox_mod):
    sb = MagicMock()
    with patch.object(inbox_mod, "_client", return_value=sb):
        inbox_mod.mark_processed("sha-ok")
    upd = sb.table.return_value.update.call_args[0][0]
    assert upd["processed_at"] is not None
    assert upd["last_error"] is None


def test_fallo_deja_la_fila_pendiente_para_redrive(inbox_mod):
    """LA PROPIEDAD CENTRAL: si el procesamiento falla, NO se marca processed_at → el re-drive
    la recupera. Antes de este fix, ese camino era el final y el mensaje se perdía."""
    sb = MagicMock()
    with patch.object(inbox_mod, "_client", return_value=sb):
        inbox_mod.mark_failed("sha-fail", "boom")
    upd = sb.table.return_value.update.call_args[0][0]
    assert upd == {"last_error": "boom"}, "no debe tocar processed_at: la fila sigue pendiente"


def test_redrive_respeta_el_lease(inbox_mod):
    """Una fila reclamada hace instantes NO se re-toma: un mensaje lento pero válido no debe
    inflar attempts ni terminar en dead-letter."""
    from datetime import datetime, timezone
    sb = MagicMock()
    ahora = datetime.now(timezone.utc).isoformat()
    sb.table.return_value.select.return_value.is_.return_value.lt.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
        data=[{"body_sha256": "s1", "tenant_id": "t1", "raw_payload": {}, "attempts": 0, "claimed_at": ahora}]
    )
    with patch.object(inbox_mod, "_client", return_value=sb):
        assert inbox_mod.redrive_once() == 0, "no debe re-drivear una fila dentro del lease"


def test_redrive_reprocesa_con_el_tenant_guardado(inbox_mod):
    """El re-drive debe usar el tenant HMAC-verificado que se guardó, NO re-resolverlo por el
    body — mantiene el cierre de cross-talk de A11/WH-01."""
    sb = MagicMock()
    sb.table.return_value.select.return_value.is_.return_value.lt.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
        data=[{"body_sha256": "s2", "tenant_id": "tenant-verificado", "raw_payload": {"e": 1},
               "attempts": 0, "claimed_at": None}]
    )
    llamadas = []
    fake = MagicMock(side_effect=lambda p, t, s: llamadas.append((p, t, s)))
    with patch.object(inbox_mod, "_client", return_value=sb), \
         patch.dict(sys.modules, {"routers.webhook": MagicMock(decouple_and_enqueue=fake)}):
        n = inbox_mod.redrive_once()
    assert n == 1
    assert llamadas[0][1] == "tenant-verificado"
    assert llamadas[0][0] == {"e": 1}
