# Known Bugs Tracker — Commerce Ops Platform

**Convención**: bugs detectados en producción / UAT que no se arreglan inmediatamente. Cada entry documenta reproducción, severidad, plan de fix, y queda en este archivo hasta cierre.

**Severidad**:
- 🔴 **alta**: bloquea flujo principal o causa pérdida de datos / dinero.
- 🟡 **media**: degrada UX o requiere workaround conocido, no bloquea.
- 🟢 **baja**: cosmético o edge case raro.

---

## BUG-105-01 — Bot pide desambiguación cuando puede inferir por sustantivo principal

**Reportado**: 2026-05-06 · UAT Sem 2 checkpoint · Founder · 🟡 media

### Reproducción

Tenant con catálogo que tiene 2+ productos con palabra común (ej. "coco" en "Aceite de Coco Virgen" + "Jabón Artesanal de Coco").

1. Cliente WhatsApp: "Quiero agregar un **aceite** de coco de 100ml"
2. Bot responde: "Tenemos varios productos relacionados: *Aceite de Coco Virgen*, *Jabón Artesanal de Coco*. Cuál te gustaría llevar?"
3. Cliente debe escribir nombre completo "Aceite de Coco Virgen" para desambiguar.

### Comportamiento esperado

Bot debería elegir "Aceite de Coco Virgen" automáticamente porque el cliente usó "**aceite**" como sustantivo principal del producto (categoría/tipo de producto). "coco" es solo ingrediente/sabor.

Heurística sugerida (intent classifier):

```
input_tokens = tokenize_lower("aceite de coco")
for product in catalog_matches:
    name_tokens = tokenize_lower(product.name)
    # Sustantivo principal del input == primera token coincidente con
    # primera token del nombre del producto.
    if input_tokens[0] == name_tokens[0]:
        return product  # match unívoco
# Solo desambiguar si más de un producto comparte sustantivo principal
```

Aplicar también para "jabón de avena", "sérum de vitamina C", etc.

### Traza DB capturada

Conversación cliente +573125835649, tenant test, 2026-05-06 ~09:21:00 GMT-5.

```
09:21:51 IN:  "Quiero Agregar un Aceite de Coco de 100ml"
09:22:00 OUT: "Tenemos varios productos relacionados: Aceite de Coco Virgen,
              Jabón Artesanal de Coco. Cuál te gustaría llevar?"
09:22:20 IN:  "Aceite de Coco Virge" ← cliente fuerza nombre completo
09:22:32 OUT: ✅ producto agregado al resumen
```

### Componente afectado

`services/ai-orchestrator/orchestrator.py` — variant detector / product matcher
(función probable `_detect_product_from_text` o equivalente — investigar cuando
se aborde el fix).

### Plan de fix

**NO fix ahora** (fuera de scope Sem 2 framework común). Candidato a:
- Sem 9 cuando se aborde Multi-agente core (I.5) — el agent "ventas" puede
  beneficiarse de esta heurística como parte del prompt builder refactor.
- O sesión dedicada UAT-fixes post-Sem-2 si afecta a más tenants.

### Workaround actual

Cliente puede escribir el nombre completo del producto. Bot también acepta
SKU si el catálogo los expone.

---

<!--
Plantilla para nuevos bugs:

## BUG-XXX-NN — Título corto

**Reportado**: YYYY-MM-DD · Origen (UAT/prod/test) · Reporter · Severidad

### Reproducción
1. ...

### Comportamiento esperado
...

### Traza DB / logs
...

### Componente afectado
...

### Plan de fix
...

### Workaround actual
...

---
-->
