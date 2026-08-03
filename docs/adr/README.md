# Índice de ADRs — Konvi Platform

> Generado 2026-08-02. Estado según cabecera declarada de cada ADR (los ADRs 0018, 0019 y 0028
> fueron actualizados a IMPLEMENTADO en esta fecha; verificación contra código en `services/`).

## ⚠️ Colisión de numeración 0023

Existen **dos ADRs con el número 0023**:

- `0023-meta-model-b-direct-provider-per-tenant.md` (Meta WhatsApp, 2026-06-03)
- `0023-shipping-provider-integration-pattern.md` (shipping provider-agnostic, 2026-05-30)

Los archivos **no se renombran** para no romper links externos/históricos. Reglas:

1. Referenciar siempre por **nombre de archivo completo**, nunca solo "ADR-0023".
2. El próximo ADR nuevo debe usar el **siguiente número libre verificado con `ls docs/adr/`**
   (a 2026-08-02: **0041**).

## Tabla de ADRs

| Número | Título | Estado |
|---|---|---|
| 0001 | [Estrategia de tier LLM (Gemini AI Studio paid + cascada + router)](0001-llm-tier-strategy.md) | Accepted (2026-04-30, rev. 81) |
| 0002 | [Cumplimiento Meta Business Policy + UX](0002-meta-business-policy-compliance.md) | Accepted (2026-04-30, rev. 84/85) |
| 0003 | [Estrategia de cumplimiento Habeas Data multi-tenant](0003-habeas-data-compliance-strategy.md) | Accepted (rev. 93–99) |
| 0004 | [Modelo SaaS B2B para módulo Contactos](0004-saas-b2b-contact-management.md) | Accepted (2026-05-02, rev. 103) |
| 0011 | [Lifecycle del payment link Wompi](0011-payment-link-lifecycle.md) | Accepted (2026-05-05, rev. 104) |
| 0015 | [Coupon Engine (Sem 6 I.2)](0015-coupon-engine.md) | Accepted (2026-05-07) |
| 0016 | [WhatsApp HSM Templates Engine (Sem 7 F2)](0016-whatsapp-hsm-templates-engine.md) | Accepted (2026-05-18) |
| 0017 | [Multi-Agent System per Tenant](0017-multi-agent-system.md) | Aprobado (2026-05-29) |
| 0018 | [Agentic Orchestrator with Hybrid LLM Tool-Use](0018-agentic-orchestrator-hybrid.md) | IMPLEMENTADO (verificado 2026-08-02) |
| 0019 | [Aveonline como provider de shipping alternativo a Envia](0019-aveonline-as-primary-shipping-provider.md) | IMPLEMENTADO (rev. 109 — Envia eliminado del runtime; verificado 2026-08-02) |
| 0020 | [Shipment lifecycle con estados ciertos (Rev. 108)](0020-shipment-lifecycle-true-state.md) | Aprobado (2026-05-25, rev. 108) |
| 0021 | [Notificaciones a operador: fuente única `notification_settings`](0021-notification-channels-unified-source.md) | ACEPTADO + IMPLEMENTADO (rev. 109) |
| 0022 | [Estrategia entidad legal, rails de cobro y mitigación patrimonial](0022-legal-entity-billing-rails-risk-mitigation.md) | ACTIVO (Fase 0 blindaje fiscal en ejecución) |
| 0023 ⚠️ | [Meta WhatsApp: Direct Provider per-tenant (Model B)](0023-meta-model-b-direct-provider-per-tenant.md) | Accepted (2026-06-03) |
| 0023 ⚠️ | [Shipping Provider Integration Pattern (provider-agnostic playbook)](0023-shipping-provider-integration-pattern.md) | ACTIVO (2026-05-30) |
| 0024 | [Criterio invariant binario/determinístico para `apply_invariants`](0024-invariant-binary-only-criterion.md) | Accepted (2026-06-23) |
| 0025 | [Estrategia de aislamiento multi-tenant: lint AST + RLS GUC](0025-multi-tenant-isolation-strategy.md) | Accepted (Fase A6) |
| 0026 | [Cart-as-SoT dueño del destino + renderizador canónico de estado](0026-cart-sot-destination-canonical-render.md) | IMPLEMENTADO (verificado en vivo) |
| 0027 | [Catálogo navegable y buscable, data-driven y multi-tenant](0027-catalog-navigable-data-driven-multitenant.md) | IMPLEMENTADO (2026-06-29) |
| 0028 | [Catálogo y carrito como servicio cross-surface](0028-catalog-cart-cross-surface-service.md) | IMPLEMENTADO (verificado 2026-08-02) |
| 0029 | [Modelo de producto multi-vertical](0029-product-model-multi-vertical.md) | DECIDIDO (2026-06-30) |
| 0030 | [Membresía single-tenant](0030-single-tenant-membership.md) | Accepted (2026-07-04) |
| 0031 | [Identidad de remitente de email: remitente único compartido](0031-single-email-sender-identity.md) | Accepted (2026-07-04) |
| 0032 | [BLOQUE 0: Endurecimiento de seguridad](0032-bloque0-security-hardening.md) | Aceptado (2026-07-10) |
| 0033 | [BLOQUE A: Integridad de dinero](0033-bloque-a-money-integrity.md) | Aceptado — items 1–5 implementados (2026-07-10) |
| 0034 | [BLOQUE B: Idempotencia de generación de guía](0034-shipment-guide-idempotency.md) | Aceptado (2026-07-10) |
| 0035 | [BLOQUE C: Decremento/reposición de stock atómico e idempotente](0035-atomic-idempotent-stock.md) | Aceptado (2026-07-11) |
| 0036 | [BLOQUE D (Mercado Libre): coherencia de stock cross-canal](0036-bloque-d-mercadolibre-stock-coherence.md) | Aceptado (2026-07-11) |
| 0037 | [Mercado Libre: reliability del spine token/webhook + roadmap](0037-meli-reliability-and-full-enablement-roadmap.md) | Aceptado (2026-07-11) |
| 0038 | [BLOQUE F post-venta: sync de estado de pedido + alerta al operador](0038-bloque-f-postventa-wiring.md) | Aceptado (2026-07-11) — implementado |
| 0039 | [BLOQUE K-2: Retiro del pipeline V1 (orchestrator legacy)](0039-bloque-k2-retiro-v1.md) | Aceptado |
| 0040 | [Comprobante de compra no fiscal](0040-comprobante-de-compra-no-fiscal.md) | IMPLEMENTADO Y EN PRODUCCIÓN (2026-07-25) |
