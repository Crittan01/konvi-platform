"""Constantes y reglas legales de dominio (Ley 1480 de 2011 — Estatuto del
Consumidor, Colombia) que la capa de dominio necesita (Track 5 M2.2).

ÚNICA fuente de estos plazos para los domain services. El bot conserva su copia
(`services/ai-orchestrator/lib/legal_texts.py` — congelado hasta el bloque bot,
que lo adopta del paquete en B-2); antes estos plazos estaban escritos a mano en
4 sitios y habían divergido.
"""
from __future__ import annotations

from typing import Optional

# Techo legal para el reembolso al comprador en comercio electrónico:
# 15 días CALENDARIO (Ley 1480 art. 47, mod. art. 3 Ley 2439 de 2024).
# El plazo de 30 días del comercio PRESENCIAL no aplica al canal online.
REEMBOLSO_DIAS_CALENDARIO_MAX = 15


def dias_reembolso(politica: Optional[dict]) -> int:
    """Plazo de reembolso prometible al comprador, con el techo legal aplicado.

    Recibe la fila de `tenant_cancellation_policy` (o None/{}). Un tenant puede
    prometer MENOS de 15 días calendario, nunca más: la promesa al comprador no
    puede exceder lo que la ley permite.
    """
    p = politica or {}
    try:
        configurado = int(p.get("manual_refund_legal_days") or REEMBOLSO_DIAS_CALENDARIO_MAX)
    except (TypeError, ValueError):
        configurado = REEMBOLSO_DIAS_CALENDARIO_MAX
    return max(1, min(REEMBOLSO_DIAS_CALENDARIO_MAX, configurado))
