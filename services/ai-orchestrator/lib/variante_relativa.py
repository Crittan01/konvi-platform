"""Referencias relativas a una variante: "el más grande", "el pequeño", "el más barato".

POR QUÉ EXISTE
El guardián anti-adivinanza rechaza que el bot elija variante si el cliente no nombró la
etiqueta ("100g", "30ml") en sus últimos mensajes. Está bien: adivinar cuál de dos
presentaciones quiere alguien es cómo se despacha lo que no pidió.

Pero es demasiado romo. En el recorrido del 2026-07-27 pasó esto:

    bot     → Jabón de Avena y Miel (60g, 100g)
    cliente → "el de avena y miel, el mas grande"
    bot     → "Cuéntame de nuevo qué producto y presentación quieres"

Le pidió repetir TODO, incluido el producto que sí había nombrado. Y "el más grande" no es
una adivinanza: es una referencia DETERMINADA sobre un conjunto que el propio bot acaba de
listar. Rechazarla no protege a nadie — solo hace que el cliente tenga que escribir dos
veces.

CÓMO SE RESUELVE, Y CUÁNDO NO
Se ordenan las variantes y se toma el extremo que pidió. Se devuelve `None` —y el guardián
sigue rechazando— en cuanto hay la menor ambigüedad:

  · la frase no trae un superlativo reconocible;
  · las etiquetas no se pueden ordenar entre sí (unidades distintas, o sin número);
  · hay empate en el extremo;
  · pidió "el mediano" y no hay exactamente tres.

Es deterministico a propósito. Un clasificador acá decidiría qué se le despacha a alguien.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Optional

#: Cómo la gente pide el extremo de un rango. Cada entrada mapea a un criterio y a qué
#: punta del orden tomar.
_SUPERLATIVOS: tuple[tuple[tuple[str, ...], str, str], ...] = (
    # (frases, criterio, extremo)
    (("mas grande", "el grande", "la grande", "mas gde", "mayor", "el de mayor",
      "mas cantidad", "mas contenido", "el mas lleno", "grandote"), "magnitud", "max"),
    (("mas pequeno", "el pequeno", "la pequena", "mas chico", "el chico", "menor",
      "el de menor", "mas chiquito", "chiquito", "el menorcito"), "magnitud", "min"),
    (("mas barato", "el barato", "mas economico", "el economico", "mas comodo",
      "menos costoso", "el de menor precio"), "precio", "min"),
    (("mas caro", "el caro", "mas costoso", "el de mayor precio",
      "el premium"), "precio", "max"),
    (("mediano", "el del medio", "intermedio"), "magnitud", "medio"),
)

#: Unidades que se pueden comparar entre sí tras normalizar a una base común.
_EQUIVALENCIAS: dict[str, tuple[str, float]] = {
    "g": ("peso", 1.0), "gr": ("peso", 1.0), "gramo": ("peso", 1.0), "gramos": ("peso", 1.0),
    "kg": ("peso", 1000.0), "kilo": ("peso", 1000.0), "kilos": ("peso", 1000.0),
    "ml": ("volumen", 1.0), "mililitro": ("volumen", 1.0), "mililitros": ("volumen", 1.0),
    "l": ("volumen", 1000.0), "lt": ("volumen", 1000.0), "litro": ("volumen", 1000.0),
    "litros": ("volumen", 1000.0),
    "un": ("unidades", 1.0), "und": ("unidades", 1.0), "unidad": ("unidades", 1.0),
    "unidades": ("unidades", 1.0), "pack": ("unidades", 1.0), "u": ("unidades", 1.0),
}

_NUMERO_UNIDAD = re.compile(r"(\d+(?:[.,]\d+)?)\s*([a-z]+)")


def _plano(texto: Any) -> str:
    """Minúsculas, sin tildes y con espacios colapsados."""
    s = str(texto or "")
    s = "".join(
        c for c in unicodedata.normalize("NFD", s.lower())
        if unicodedata.category(c) != "Mn"
    )
    return " ".join(s.split())


def _magnitud(label: Any) -> Optional[tuple[str, float]]:
    """(dimensión, valor en unidad base) de una etiqueta como "100g" o "1.5 L".

    `None` si no hay un número con unidad reconocible: sin eso no hay orden que valga y
    hay que devolverle la decisión al cliente.
    """
    m = _NUMERO_UNIDAD.search(_plano(label))
    if not m:
        return None
    equiv = _EQUIVALENCIAS.get(m.group(2))
    if not equiv:
        return None
    dimension, factor = equiv
    try:
        return dimension, float(m.group(1).replace(",", ".")) * factor
    except ValueError:
        return None


def _precio(v: dict) -> Optional[float]:
    for clave in ("price", "unit_price", "precio", "price_cents", "unit_price_cents"):
        if v.get(clave) is None:
            continue
        try:
            valor = float(v[clave])
        except (TypeError, ValueError):
            continue
        return valor / 100.0 if clave.endswith("_cents") else valor
    return None


def detectar_superlativo(frase: str) -> Optional[tuple[str, str]]:
    """(criterio, extremo) que pide la frase, o None si no pide ninguno."""
    p = _plano(frase)
    for frases, criterio, extremo in _SUPERLATIVOS:
        if any(f in p for f in frases):
            return criterio, extremo
    return None


def resolver_variante_relativa(
    frase: str,
    variantes: list[dict],
) -> Optional[dict]:
    """La variante que el cliente pidió por referencia relativa, o None.

    `None` significa "no me consta" y el guardián anti-adivinanza sigue mandando. Es la
    respuesta correcta ante cualquier duda: el costo de equivocarse acá es despacharle a
    alguien algo que no pidió.
    """
    if not frase or not variantes or len(variantes) < 2:
        return None

    detectado = detectar_superlativo(frase)
    if not detectado:
        return None
    criterio, extremo = detectado

    if criterio == "magnitud":
        magnitudes = [(_magnitud(v.get("label")), v) for v in variantes]
        if any(m is None for m, _ in magnitudes):
            return None                       # alguna etiqueta no tiene número: sin orden
        dimensiones = {m[0] for m, _ in magnitudes}
        if len(dimensiones) > 1:
            return None                       # gramos contra mililitros: no comparan
        ordenables = [(m[1], v) for m, v in magnitudes]
    else:
        precios = [(_precio(v), v) for v in variantes]
        if any(p is None for p, _ in precios):
            return None
        ordenables = [(p, v) for p, v in precios]

    ordenables.sort(key=lambda par: par[0])

    if extremo == "medio":
        # "El mediano" solo es una referencia determinada con exactamente tres opciones.
        # Con cuatro, "el del medio" no señala ninguna.
        if len(ordenables) != 3:
            return None
        return ordenables[1][1]

    elegido = ordenables[-1] if extremo == "max" else ordenables[0]
    # Empate en el extremo: "el más grande" no señala a ninguna de las dos.
    if sum(1 for valor, _ in ordenables if valor == elegido[0]) > 1:
        return None
    return elegido[1]
