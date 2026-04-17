# Render Free → Starter: Análisis y Path de Upgrade

Última actualización: 2026-04-16

---

## Estado actual

Los 4 servicios corren en **Render Free plan**. Esto es adecuado para desarrollo y alpha interno, pero tiene limitaciones reales que afectan la experiencia en producción con tenants reales.

---

## Limitaciones del plan Free que afectan este proyecto

### 1. Cold starts (el más crítico)

Render Free **duerme el servicio tras 15 minutos de inactividad**. Al recibir la primera petición, tarda 30-60 segundos en despertar.

| Servicio | Impacto del cold start |
|---------|----------------------|
| `commerce-ops-web` | Usuario ve pantalla en blanco o timeout. Inaceptable en producción. |
| `commerce-ops-connector` | Un webhook de Meta que llega durante el cold start **se pierde**. Mensaje del cliente no procesado. |
| `commerce-ops-api` | Requests del frontend fallan o hacen timeout. |
| `commerce-ops-orchestrator` | El polling se detiene. Mensajes pendientes no se procesan hasta que despierte. |

> El orchestrator tiene el workaround de daemon thread + `/health` endpoint para que Render no lo duerma, pero en Free este mecanismo no es confiable si no hay tráfico externo.

### 2. Sin workers nativos

`type: worker` no está disponible en Free. El orchestrator usa el workaround de `type: web` + daemon thread en `server.py`. Esto:
- Consume RAM adicional del proceso FastAPI
- No es el patrón correcto para un worker de background
- En Starter, el orchestrator debería ser `type: worker` nativo

### 3. RAM limitada (512MB)

El build de Next.js requería `NODE_OPTIONS='--max-old-space-size=460'` para no hacer OOM durante la compilación. En Starter (2GB RAM), esta restricción no es necesaria.

### 4. Disco efímero

Render Free tiene disco efímero — cualquier archivo escrito al sistema de archivos se pierde en el siguiente deploy. No afecta actualmente (no usamos disco), pero limita opciones futuras.

### 5. Sin SLA ni soporte prioritario

En producción real, un down de 30 minutos no tiene escalación disponible en Free.

---

## Comparativa Free vs Starter

| Característica | Free | Starter ($7/servicio/mes) |
|---------------|------|--------------------------|
| Cold starts | ✅ Sí (15 min inactividad) | ❌ No (always-on) |
| RAM | 512MB | 512MB (mismo, sin OOM en build) |
| `type: worker` | ❌ No disponible | ✅ Disponible |
| SLA | ❌ Sin SLA | ✅ 99.9% uptime |
| Soporte | Comunidad | Email |
| Custom domains | ✅ | ✅ |
| Costo mensual (4 servicios) | $0 | ~$28/mes |

> Fuente: verificar en https://render.com/pricing (precios pueden cambiar)

---

## DECISION FINAL

**No se hace el upgrade ahora.** El upgrade a Starter es la decisión correcta **antes de onboardear el primer tenant real en Beta**, no antes.

**Criterio de trigger para upgrade:**
- La certificación funcional v2 está completa (18 módulos verificados)
- Hay al menos 1 tenant real a punto de operar
- O se detectan cold starts que interrumpen operaciones reales

---

## VALIDAR EN DOCUMENTACION OFICIAL

- Precios Render Starter: https://render.com/pricing
- `type: worker` en Starter: https://render.com/docs/background-workers
- Límites Render Free: https://render.com/docs/free#free-web-services

---

## RIESGO

| Riesgo | Descripción |
|--------|------------|
| Cold start en connector | Webhook de WhatsApp llega durante cold start → mensaje perdido |
| Cold start en orchestrator | Polling interrumpido → respuesta IA tardía |
| No hay alertas automáticas | Si un servicio cae en Free, no hay notificación proactiva |

---

## IMPACTO OPERATIVO del upgrade

Si se decide hacer upgrade a Starter:

### Cambios en render.yaml

```yaml
# Cambiar en cada servicio:
plan: free
# →
plan: starter
```

### Cambio en orchestrator (después del upgrade)

```yaml
# Cambiar commerce-ops-orchestrator de:
- type: web
  startCommand: uvicorn server:app --host 0.0.0.0 --port $PORT
# →
- type: worker
  startCommand: python3 main.py
```

Y revertir `server.py` (el wrapper con daemon thread) para que `main.py` sea el entrypoint directo.

---

## INTERVENCION HUMANA REQUERIDA (cuando se decida hacer el upgrade)

**RESPONSABLE**: Owner del proyecto / DevOps

**MOMENTO**: Antes de onboardear primer tenant real en Beta Controlada

**PASOS**:
1. Render Dashboard → Billing → Actualizar plan de cuenta
2. En `render.yaml`: cambiar `plan: free` → `plan: starter` en los 4 servicios
3. Commit + push a `main` → Render aplica el nuevo plan en el siguiente deploy
4. Verificar que los 4 servicios están always-on (sin cold start en el primer request tras inactividad)
5. Para el orchestrator: cambiar a `type: worker` + `startCommand: python3 main.py` (eliminar el wrapper de server.py)

**INSUMOS**: Tarjeta de crédito registrada en Render. ~$28/mes.

**CRITERIO DE ÉXITO**: Ningún servicio hace cold start tras 30 minutos de inactividad.

---

## Alternativas evaluadas

| Alternativa | Pros | Contras | Decisión |
|-------------|------|---------|---------|
| Render Starter | Simple, mismo stack | $28/mes, aún limitado | ✅ Recomendado para Beta |
| Render Pro | Más RAM, auto-scaling | $85+/mes | Overkill para Beta |
| Fly.io | Más flexible, cheaper | Migración completa | No justificado ahora |
| Railway | Similar Render | Menos docs, menos estable | No |
| AWS ECS/Fargate | Full control | Complejidad operativa alta | Futuro (RC o producción) |
