# Próximos Pasos

> **Verificado contra repo**: 2026-08-02 @ `5fdad396` (develop).

**El backlog de verdad es [`docs/PLAN.md`](../docs/PLAN.md)** — checklist go-live, backlog
P0/P1/P2/P3, roadmap post-go-live y rituales operativos, alimentado por la
[auditoría consolidada 2026-08-02](../.audit/findings/2026-08-02-consolidated-audit.md)
(IDs B/A/M con evidencia `archivo:línea`). Este archivo solo conserva (1) lo que PLAN.md no
cubre o necesita contexto extra y (2) el registro de lo verificado-resuelto en la limpieza
de hoy. **No duplicar aquí ítems que ya están en PLAN.md.**

---

## Verificado-resuelto 2026-08-02 (antes listado aquí como pendiente)

| Ítem | Evidencia |
|---|---|
| Gate gemini-3.x + Next 15 (incl. sus pasos IH) | Desplegado: producción a la par de develop; `GEMINI_MODEL=gemini-3.1-flash-lite` en `render.yaml` |
| P0 Sem 6 — re-uso framework común para HSM | Obsoleto: HSM templates ya implementado end-to-end |
| F2 WhatsApp HSM templates (F2.1–F2.6) | Implementado: schema `whatsapp_templates`, webhook `message_template_status_update`, `send_template`, UI en `/dashboard/integrations/whatsapp?tab=plantillas`. Solo queda F2.7 (abajo) |
| Rev. 74 cutover V2 (Fases D/E) | Plan **cancelado** en rev. 75: V2 eliminado; path único = orchestrator agentic |
| Model B Phase 7 (founder) | Connector Model B live en prod; WhatsApp funciona en ambos tenants |
| A6.2.7 aislamiento multi-tenant | 0 gaps en 248 archivos, ratchet CI (`scripts/audit_tenant_filter.py`) |
| A7 RBAC ai_agents / marketplace | Cerrado (owner-only en server actions) |
| ADR-0003 follow-ups F1, F4, F5, F6, F7 | Implementados en código: SAR printable (`data_subject_request.py:407`), UI retención, reporte SIC (`sic_report.py`), detector rectificación, click-wrap legal (`settings/legal`). Quedan solo F2/F3 → PLAN P2 |
| G-7 / G-8 legal | PRs #195/#197 mergeados |
| Comprobante ADR-0040 | En prod (#180-#186), `/dashboard/receipts` |
| M3 AI Agents router | Resuelto |
| Migraciones bloques 2026-04 "pendientes de aplicar" | Todas aplicadas: ledger 251 repo = prod, cero drift |
| Envia Fase 2 (labels/pickup/webhooks/DANE dinámico) | Muerto: Envia eliminado del runtime en rev. 109 |

---

## Lo que PLAN.md no cubre (o necesita contexto extra)

### F2.7 — UAT HSM con 2 tenants piloto (único remanente de F2)

Onboarding manual de 2 de los 6 tenants que requieren proactivos fuera de la CSW de 24h
(~2 días). Dependencia: plantillas aprobadas en el Meta Business Manager de cada tenant
(PLAN.md checklist #11, founder-gate).

### H7 — rotación de credenciales (founder) — detalle operativo

PLAN B2 lo lista; el detalle: rotar service_role key, anon key, DB password, Meta App
Secret y Wompi keys del proyecto Supabase `***SUPABASE_PROJECT_REF_REDACTED***`. Razón: el commit
histórico `be739a4` (2026-04-06) tenía un `.env` con plaintext de estos secretos; `488c6c6`
lo removió del tracking, pero la historia git permanece pushed a GitHub. H8
(`git filter-repo`) queda opcional — PLAN P3.

### Fase 0 fiscal — hard constraints y triggers SAS (contexto de PLAN B6)

PLAN B6 lista las 7 acciones founder. Aquí quedan solo los constraints de fondo (ADR-0022):

1. **Correo Wompi inmutable** — pensar bien el correo definitivo.
2. **UNA cuenta Wompi = UN nombre comercial** — el cliente final ve "KONVI" en el extracto.
3. **Wompi NO marketplace** — Konvi NO recibe pagos para terceros (sería intermediación financiera regulada SFC).
4. **Persona natural = patrimonio personal ilimitado** — mitigar Capa 1 (contratos) + Capa 2 (seguros) obligatorias.
5. **Facturación electrónica DIAN desde el primer peso**.
6. **RST 2027** — ventana cierra 28-feb-2027.

Triggers SAS (cualquiera activa migración persona natural → SAS): ingresos founder
≥ $10M COP/mes × 3 meses · tenant enterprise exige sociedad · capital externo ·
ingresos consolidados cruzan 3.500 UVT · vertical propia >$5M/mes sostenida.

### Konvi Studio — contexto del gate (PLAN §C)

Gate comercial duro: Lucams (tenant piloto de productos personalizables) valida demanda
con flow manual (Instagram + WhatsApp + Wompi link + diseño a mano) hasta **>30 órdenes/mes**.
NO arrancar antes. Si se dispara: editor canvas (react-konva), preview 3D, design assistant,
3 buckets storage per-tenant, `cart_items.custom_design` — estimado ~6-8 semanas.

### COD H.2.4 — evidencia certificada de la pausa (PLAN §C)

Pausado formalmente 2026-05-07. Certificado: 4 carriers COD viables en Colombia
(servientrega, tcc, fedex, dhl); no existe webhook COD dedicado del carrier. Bloqueantes
de reanudación: KYC Ecart Pay Colombia + prueba real en producción + confirmación de
formato DANE Servientrega (V.4) + habilitación Coordinadora.

### Backlog menor no cubierto por PLAN (sin re-verificar 2026-08-02 — verificar antes de ejecutar)

- **MeLi**: tracking de `order_tracking` en detalle de pedido; paginación completa de listings; Q&A + topics de mensajes (auto-reply post-venta).
- **Plataforma**: multi-agente per-tenant (I.5) · Storefront base (I.1) · Channel Registry Messenger/Instagram (I.3) · Onboarding Wizard (MA-4) · billing aggregator (MA-5) · logs forensics append-only (MA-8).
- **Cupones**: tipos de descuento extendidos (`percent_on_total`, `percent_on_shipping`) — trigger: 2-3 tenants pidiéndolo (extiende ADR-0015).
- **Tiering**: decisión comercial de límites/exclusividades por plan + política grace/overage (IH founder).
- **Higiene**: retirar fallback legacy `NEXT_PUBLIC_API_URL` del código server-side.
- **Bot/Habeas Data** (rev. 102): flujo representante legal para menores · i18n bot no-CO · upload evidencia física canal `in_person` · reporte SIC enriquecido.
- **Inbox**: visual de carrito + pedidos recientes del contacto (F-Inbox-1) · persistir `shipping_carrier` en la orden (F-Order-1).

### ADRs activos (leer antes de tocar LLM / Meta / Habeas Data)

- [ADR-0001](../docs/adr/0001-llm-tier-strategy.md) — cascada LLM + triggers concretos (§7) para revisitar scaling.
- [ADR-0002](../docs/adr/0002-meta-business-policy-compliance.md) — detectores pre-LLM (healthcare, drugs, sensitive payment).
- [ADR-0003](../docs/adr/0003-habeas-data-compliance-strategy.md) — cumplimiento Habeas Data end-to-end (D1-D7).
- Índice completo: [`docs/adr/README.md`](../docs/adr/README.md).

---

## Histórico

Este archivo ya no lleva log de sesiones. El detalle de cierres anteriores a 2026-08-02
vive en `.context/01-state.md` y en `docs/_archive/`.
