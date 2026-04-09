# Modelo de Auditoría — Commerce Ops Platform

Última actualización: 2026-04-09

---

## Estado

❌ **Pendiente de implementación**

La auditoría es un requisito del producto (módulo A.12 de Tenant Console y B.8 de Platform Console) pero la tabla y los mecanismos aún no están implementados.

---

## Propósito

Proporcionar trazabilidad completa de:
- Qué usuario realizó qué acción
- En qué recurso y tenant
- En qué momento
- Con qué resultado

Esto es necesario para:
- Seguridad y cumplimiento (quién accedió a qué)
- Soporte operativo (rastrear problemas)
- Auditoría de accesos de soporte de plataforma a datos de tenants

---

## Diseño de la tabla `audit_log`

```sql
-- Pendiente — migración a crear
CREATE TABLE public.audit_log (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       UUID REFERENCES tenants(id),   -- NULL para acciones de plataforma global
  user_id         UUID REFERENCES auth.users(id), -- NULL para workers automáticos
  action          TEXT NOT NULL,
  resource_type   TEXT,   -- product, conversation, order, shipment, tenant_user...
  resource_id     UUID,
  old_data        JSONB,  -- snapshot anterior (para updates/deletes)
  new_data        JSONB,  -- snapshot nuevo (para inserts/updates)
  metadata        JSONB,  -- contexto adicional (IP, user-agent, etc.)
  ip_address      TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- RLS: tenant ve su propia auditoría; platform ve todo
ALTER TABLE public.audit_log ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Tenant Audit Access"
  ON public.audit_log FOR SELECT
  USING (tenant_id = app_current_tenant() OR tenant_id IS NULL);
```

---

## Convenciones de `action`

```
resource.verb

Ejemplos:
  product.create
  product.update
  product.delete
  conversation.takeover
  conversation.close
  order.create
  order.status_update
  shipment.quote
  shipment.label_create
  tenant_user.invite
  tenant_user.role_change
  platform.tenant_access    -- cuando soporte accede a un tenant
```

---

## Mecanismos de escritura

### 1. Triggers de PostgreSQL (para mutaciones críticas)

Para tablas de datos críticos, implementar triggers que inserten en `audit_log` automáticamente:

```sql
-- Ejemplo: trigger en products
CREATE OR REPLACE FUNCTION audit_products_changes()
RETURNS TRIGGER AS $$
BEGIN
  INSERT INTO public.audit_log (tenant_id, action, resource_type, resource_id, old_data, new_data)
  VALUES (
    NEW.tenant_id,
    TG_OP::TEXT || '.product',
    'product',
    NEW.id,
    row_to_json(OLD),
    row_to_json(NEW)
  );
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
```

### 2. Escritura explícita desde API Gateway

Para acciones de usuario que no son simples mutaciones de DB (ej: human takeover, acceso de soporte):

```python
# En services/api, después de cada operación exitosa
await audit.log(
    tenant_id=tenant_id,
    user_id=current_user.id,
    action="conversation.takeover",
    resource_type="conversation",
    resource_id=conversation_id,
    metadata={"source": "inbox_ui"}
)
```

---

## Acceso de soporte de plataforma

Cuando un operador de Platform Console accede a datos de un tenant específico:
1. Se inserta en `audit_log` con `action = 'platform.tenant_access'`
2. `tenant_id` = el tenant accedido
3. `user_id` = el operador de soporte
4. El tenant puede ver esta entrada en su propia auditoría

---

## Retención de datos

- Auditoría de negocio: retener mínimo 12 meses
- Auditoría de seguridad (accesos de soporte): retener mínimo 24 meses
- Implementar particionado por mes si el volumen lo justifica

---

## Prioridad de implementación

Implementar junto con RBAC completo en `services/api` (Post-Fase 8).
El riesgo R-10 está activo hasta entonces.

---

## Documentos relacionados

- `docs/data/schema.md` — Diseño de la tabla audit_log
- `docs/risks/risk-register.md` — R-10 (auditoría pendiente)
- `docs/product/admin-ui-modules.md` — A.12 Auditoría, B.8 Auditoría Global
