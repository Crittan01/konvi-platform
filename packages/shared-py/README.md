# konvi-domain (`packages/shared-py/`)

Capa de dominio compartida de Konvi Platform (Track 5 — dominios modulares).
**Una sola implementación de cada capacidad de dominio**, consumida in-process
por `services/api` y `services/ai-orchestrator` (los rootDirs separados de Render
impiden importarse entre sí — antes esto se resolvía copiando archivos o con
sys.path hacks; este paquete mata ambas deudas).

Contrato y decisiones de diseño (aprobado founder 2026-08-25):
[`docs/architecture/domain-services-contract.md`](../../docs/architecture/domain-services-contract.md)
· Inventario M1:
[`docs/architecture/domain-capabilities-inventory.md`](../../docs/architecture/domain-capabilities-inventory.md)

## Contenido

- `konvi_domain.coupons` — motor de cupones ADR-0015 (extraído de
  `services/api/lib/coupons.py` en M2.0; los shims `lib/coupons.py` de ambos
  servicios re-exportan desde aquí — única fuente).
- `konvi_domain.actor` — `Actor` de primer ciudadano (channel/role/tenant).
- `konvi_domain.errors` — `DomainError` + códigos estables.
- `konvi_domain.events` — `DomainEvent` (bus = infra existente: cart_events,
  audit_log, messages; no hay bus nuevo).

## Instalación

```bash
# Local (VM sin venv — user site):
pip install --user -e packages/shared-py        # o: make -C .local deps

# CI: paso explícito `pip install -e packages/shared-py` (CWD = repo root).
# Render: buildCommand de cada servicio `pip install -e ../../packages/shared-py`
# (CWD = rootDir del servicio). OJO: pip resuelve la ruta -e relativa al CWD,
# NO al requirements.txt — verificado empíricamente (M2.0); por eso NO va en
# requirements.txt sino en el buildCommand.
```

## Reglas

- Nada de lógica cross-tenant: `tenant_id` siempre explícito (Platform Console
  Fase 12 es consumidora futura).
- Los puntos transaccionales atómicos/idempotentes siguen en SQL/RPC
  (patrón ADR-0040); el paquete delega, no reimplementa.
- Importar el paquete no tiene efectos colaterales (M3 lee contratos sin
  levantar nada).
