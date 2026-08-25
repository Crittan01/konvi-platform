# Arquitectura destino — Konvi como plataforma modular de dominios (visión 2026-08-22)

> Origen: directiva founder 2026-08-22 — "el BOT es el core, pero TODO el ecosistema está conectado: productos, categorías, pedidos, contactos, cotizador, promociones, reclamos, comprobantes, compras, finanzas, analítica… y el bot debe conversar sobre todos ellos. La solución es para CUALQUIER e-commerce (tecnología, juguetería, ropa…) — debe ser tan modular que sea un todo." Este documento fija la arquitectura destino y cómo llegamos sin romper lo que ya está certificado.

## 1. Principio rector

**Los dominios son la fuente de verdad; los canales son reemplazables.** Hoy hay dos canales (consola web + bot WhatsApp) que hablan con los módulos por caminos distintos: la consola vía API REST, el bot vía tools ad-hoc escritas a mano por dominio. El destino es UN SOLO camino:

```
                 ┌─────────────┐   ┌──────────────┐   ┌─────────────┐
                 │ Consola web │   │ Bot WhatsApp │   │ Canales     │
                 │             │   │ (Telegram,   │   │ futuros     │
                 │             │   │  voz, …)     │   │ (API pub.)  │
                 └──────┬──────┘   └──────┬───────┘   └──────┬──────┘
                        │ REST            │ tools             │
                        ▼                 ▼                   ▼
                 ┌────────────────────────────────────────────────┐
                 │        DOMAIN SERVICES (una sola verdad)        │
                 │  catálogo · pedidos · contactos · envíos ·      │
                 │  promociones/cupones · reclamos · comprobantes ·│
                 │  compras · finanzas · analítica · stock         │
                 └───────────────────────┬────────────────────────┘
                                         ▼
                                 Postgres + RLS (tenant_id)
```

- **La capacidad de un dominio se define UNA VEZ** (contrato del domain service) y queda disponible para cualquier canal: la consola la usa por REST, el bot por una tool GENERADA del contrato (no escrita a mano por canal).
- **El bot deja de tener "tools sueltas" y pasa a tener "capacidades de dominio conversables"**: stock, cupones, reclamos, promociones, comprobantes… todas responden al mismo contrato, y el FSM del bot (B-2, state handlers) las orquesta.

## 2. Qué ya existe y es cimiento (no se toca)

- Multi-tenant real con RLS y Vault per-tenant.
- Catálogo **data-driven por atributos** (ADR-0027) — ya soporta cualquier vertical sin código nuevo (ropa: talla/color; tecnología: memoria/pantalla; juguetería: edad…).
- Módulos de consola ya vivos: productos, categorías, pedidos, contactos, envíos, reclamos, comprobantes, compras, finanzas, analítica, cupones.
- Bot con invariants de dinero/verdad y tools batalladas (B-0 certificado 2026-08-22).
- Plan capabilities per-tenant (gates por plan) — embrión de los "packs".

## 3. Qué falta (los gaps honestos)

1. **Cobertura del bot por dominio, hoy parcial y artesanal**: reclamos/cupones/stock tienen acceso desigual desde el chat; compras/finanzas/analítica no son conversables; cada tool se escribió a mano y diverge.
2. **Sin contrato de dominio único**: la consola y el bot no comparten una capa de servicios; la lógica vive en routers + tools por separado (drift garantizado — ya lo vimos con los espejos).
3. **Sin packs de vertical**: habilitar un e-commerce de ropa vs tecnología hoy es config manual de categorías/atributos, no un "pack" activable (flujos, atributos, políticas de envío/devolución, tono del bot por vertical).
4. **Analítica no conversacional**: "¿cómo van mis ventas esta semana?" debería ser una pregunta al bot (dueño) — hoy no hay canal.

## 4. Fases (se apoyan en B-0…B-4, no los reemplazan)

- **M1 — Inventario de capacidades por dominio (agente):** matriz dominio × (consola / bot / contrato existente). Detecta qué dominios ya tienen lógica reutilizable y cuáles solo viven en routers. Salida: el backlog exacto de la capa de servicios. **✅ ENTREGADO 2026-08-24 → [`domain-capabilities-inventory.md`](domain-capabilities-inventory.md)** (11 dominios, evidencia `archivo:línea`, backlog priorizado de 11 domain services).
- **M2 — Contrato de domain services (agente, diseño + primeros 2 dominios):** definir el contrato (`DomainCapability`: acciones, validaciones, eventos) y migrar 2 dominios piloto (pedidos + reclamos) a services compartidos consumidos por router y tool a la vez. Con tests de paridad canal↔canal. **Diseño propuesto 2026-08-24 → [`domain-services-contract.md`](domain-services-contract.md) — pendiente visto bueno founder (4 preguntas abiertas §8) antes de escribir código de producción.**
- **M3 — Tooling generativo del bot (agente):** las tools del bot se generan/adaptan desde el contrato de dominio (schema + descripción para el LLM incluidos en el contrato). El subset por estado (B-2) referencia capacidades, no funciones.
- **M4 — Packs de vertical (diseño con founder):** pack = categorías+atributos+políticas+preset de bot por tipo de tienda (belleza/moda/tecnología/juguetería…). Activación por tenant al onboarding.
- **M5 — Analítica conversacional (owner):** preguntas de negocio al bot por WhatsApp/Telegram (ventas, top productos, pedidos pendientes) sobre métricas ya existentes.

## 5. Relación con el plan vigente

- B-0 (hecho) → B-1 (calidad conversacional) → B-2 (state handlers) siguen igual; M1-M5 se insertan DESPUÉS de B-2 (los state handlers consumen capacidades de dominio).
- B-3/B-4 (eval harness + observabilidad) aplican también a los dominios nuevos.
- Nada de esto toca PRD hasta certificar en STG (regla vigente).

Registrado en `docs/PLAN-CIERRE.md` como Track 5.
