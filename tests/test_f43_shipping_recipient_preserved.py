"""F43 — el destinatario alterno (shipping_meta.recipient, envío a tercero, Ley 1581 BUG 37) NO
debe perderse al reconstruir shipping_meta.

invalidate_shipping corre en CADA add_item/remove_item y set_shipping_city al cambiar de ciudad;
ambos reconstruían shipping_meta sin preservar 'recipient' → el resumen mostraba al titular WhatsApp
como receptor. Guarda source-based (cart_tool tiene deps pesadas), estilo fitness-test del repo.
"""
from pathlib import Path
import re

_SRC = (Path(__file__).resolve().parents[1]
        / "services/ai-orchestrator/tools/cart_tool.py").read_text()


def test_invalidate_shipping_preserva_recipient():
    # El tuple de campos preservados en invalidate_shipping debe incluir 'recipient'.
    m = re.search(r'for k in \(("city"[^)]*)\)', _SRC)
    assert m and '"recipient"' in m.group(1), \
        "invalidate_shipping debe preservar 'recipient' en el tuple de campos"


def test_set_shipping_city_preserva_recipient():
    # new_meta en set_shipping_city debe incluir la key 'recipient'.
    assert '"recipient": meta.get("recipient")' in _SRC, \
        "set_shipping_city debe preservar recipient en new_meta"
