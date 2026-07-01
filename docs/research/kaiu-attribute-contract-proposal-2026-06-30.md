# Propuesta de contrato de atributos — KAIU (ADR-0029 F1, curaduría núcleo cosmética)

**Estado:** PROPUESTA para confirmación del founder (D3 — núcleo curado por Konvi).
**Fecha:** 2026-06-30 · **Grounding:** dominio cosmético/aromaterapia + patrón tipado Shopify (metric con
unidad, select con enum, `is_variant_axis`).
**Cómo leer:** cada categoría operativa de KAIU se mapea a un nodo de la taxonomía (a confirmar) y define
sus atributos tipados. `is_variant_axis=SÍ` = ese atributo **crea variantes** (SKU/precio/stock distintos);
el resto son **descriptivos**. `req` = requerido. Los valores `select` son enums cerrados (anti-alucinación).

> **La clave del modelo:** hoy el "tamaño" de KAIU vive en 3 claves inconsistentes (Volumen/Presentación/
> Contenido). En TODAS las categorías físicas, el **eje de variante es el tamaño** (volumen ml / peso g) —
> se unifica a UN atributo tipado `metric`. El resto describe.

---

## 1. Aceites Esenciales
**Nodo taxonomía (confirmar):** Health & Beauty > Health Care > Aromatherapy.

| code | label | type | unit | variant-axis | req | valores permitidos |
|---|---|---|---|---|---|---|
| `volume` | Volumen | metric | ml | **SÍ** | sí | 10, 30 *(+ los que uses)* |
| `purity` | Pureza | select | — | no | sí | 100% puro · Diluido |
| `botanical_name` | Nombre botánico | text | — | no | no | *(ej. Lavandula angustifolia)* |
| `extraction_method` | Extracción | select | — | no | no | Destilación al vapor · Prensado en frío |
| `usage_mode` | Modo de uso | select | — | no | no | Difusión · Tópico diluido · Aromaterapia |
| `benefits` | Beneficios | text (**GOBERNADO**) | — | no | no | *(claims aprobados + disclaimer — validar INVIMA/Ley 1480)* |

## 2. Aceites Vegetales (portadores)
**Nodo (confirmar):** Health & Beauty > Personal Care > Cosmetics > Skin Care.

| code | label | type | unit | variant-axis | req | valores |
|---|---|---|---|---|---|---|
| `volume` | Volumen | metric | ml | **SÍ** | sí | 30, 60, 120 |
| `pressing` | Prensado | select | — | no | no | Prensado en frío · Refinado |
| `botanical_name` | Nombre botánico | text | — | no | no | — |
| `benefits` | Beneficios | text (**GOBERNADO**) | — | no | no | *(claims aprobados)* |

## 3. Jabones Artesanales
**Nodo (confirmar):** Health & Beauty > Personal Care > Cosmetics > Bath & Body > Bar Soap.

| code | label | type | unit | variant-axis | req | valores |
|---|---|---|---|---|---|---|
| `weight` | Peso | metric | g | **SÍ** | sí | 60, 100 |
| `scent` | Aroma | select | — | *decisión†* | no | Lavanda · Coco · Neutro |
| `skin_type` | Tipo de piel | select | — | no | no | Todo tipo · Seca · Grasa · Sensible |
| `ingredients` | Ingredientes | text | — | no | no | — |
| `benefits` | Beneficios | text (**GOBERNADO**) | — | no | no | — |

## 4. Sérums
**Nodo (confirmar):** Health & Beauty > Personal Care > Cosmetics > Skin Care > Facial Serum.

| code | label | type | unit | variant-axis | req | valores |
|---|---|---|---|---|---|---|
| `volume` | Volumen | metric | ml | **SÍ** | sí | 15, 30 |
| `active_ingredient` | Ingrediente activo | select | — | no | no | Vitamina C · Ácido hialurónico · Retinol |
| `skin_type` | Tipo de piel | select | — | no | no | Todo tipo · Seca · Grasa · Sensible |
| `benefits` | Beneficios | text (**GOBERNADO**) | — | no | no | — |

## 5. Kits
**Nodo (confirmar):** Health & Beauty > Personal Care (bundle).

| code | label | type | unit | variant-axis | req | valores |
|---|---|---|---|---|---|---|
| `theme` | Temática | select | — | no | no | Inicio · Relajación · Cuidado facial |
| `contents` | Contenido | text | — | no | no | *(lista de productos incluidos)* |

---

## Decisiones puntuales que necesito de ti

† **Aroma en jabones (`scent`)** — ¿lo vendes *por aroma* (cada aroma es un SKU/variante distinto) o el
aroma solo describe un jabón fijo? En el modelo Shopify, un atributo es eje-de-variante **por producto**:
un jabón "Lavanda 60g/100g" tiene el peso como eje; si además vendes "Coco vs Lavanda" como opciones del
mismo producto, `scent` también es eje. Confírmame el caso real de KAIU.

**Beneficios (`benefits`, campo GOBERNADO)** — este es el que blinda lo legal: el bot **solo** puede
emitir beneficios desde aquí (nunca inventar). Necesito de ti/legal **qué claims** son válidos para tus
aceites esenciales/bienestar (INVIMA / Ley 1480) + el disclaimer obligatorio. Sin eso, el campo queda
vacío y el bot no afirma beneficios (fail-safe correcto).

**Valores permitidos** — puse los que se ven en tu catálogo actual + los típicos; ajústalos a los reales
(tamaños que manejas, aromas, ingredientes activos).

---

Al confirmar (o ajustar), lo convierto en el **seed** de `category_attributes`/`attribute_values` y, junto
con la migración `20260630120000_adr0029_f0f1_attribute_contract.sql`, aplicamos F0+F1 con tu autorización.
