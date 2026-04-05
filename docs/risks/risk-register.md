# Risk Register

## Riesgo 1
### Nombre
Fuga de datos entre tenants

### Impacto
Muy alto

### Probabilidad inicial
Media

### Mitigación
- tenant_id
- RLS
- RBAC
- claims/JWT
- storage segregado
- auditoría
- revisión de tools y queries

---

## Riesgo 2
### Nombre
Dependencia excesiva del LLM

### Impacto
Alto

### Probabilidad inicial
Media

### Mitigación
- tools obligatorias para verdad transaccional
- structured outputs
- handoff
- guardrails
- fallback seguro

---

## Riesgo 3
### Nombre
Complejidad innecesaria de infraestructura

### Impacto
Medio/alto

### Probabilidad inicial
Media

### Mitigación
- mantener Supabase + Render como base
- evitar Redis y piezas extras sin justificar
- introducir nuevos componentes solo con evidencia

---

## Riesgo 4
### Nombre
Integración frágil con Mercado Libre

### Impacto
Alto

### Probabilidad inicial
Media

### Mitigación
- mapping explícito
- sync_runs
- sync_errors
- reconciliación periódica
- idempotencia
- auditoría

---

## Riesgo 5
### Nombre
Problemas de onboarding en WhatsApp / Meta

### Impacto
Alto

### Probabilidad inicial
Media

### Mitigación
- documentar intervención humana
- checklist de onboarding
- separar tareas manuales de tareas técnicas
- validar flujo completo antes de producción

---

## Riesgo 6
### Nombre
Media no persistida o expirada

### Impacto
Medio

### Probabilidad inicial
Media

### Mitigación
- descarga temprana
- worker dedicado
- storage policies
- retries controlados

---

## Riesgo 7
### Nombre
Diseño documental insuficiente antes de implementar

### Impacto
Alto

### Probabilidad inicial
Media

### Mitigación
- blueprint completo
- decisiones validadas
- pendientes explícitos
- revisión humana antes de scaffold técnico

---

## Riesgo 8
### Nombre
Costos subestimados por mala separación entre local y producción

### Impacto
Medio

### Probabilidad inicial
Media

### Mitigación
- local bien aislado
- prod mínima pero seria
- staging solo cuando ya aporte valor real
- control de piezas y servicios