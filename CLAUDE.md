# CLAUDE.md — Commerce Ops Platform

Este archivo define el contexto estable del proyecto.
Usarlo para entender arquitectura, restricciones, stack, convenciones y prioridades antes de proponer o aplicar cambios.
No sustituye validaciones en código, documentación oficial ni checks del repositorio.

## Qué es este proyecto

SaaS conversacional multi-tenant para e-commerce B2B2C vía WhatsApp.
Cada empresa (tenant) opera en aislamiento total.
El canal de ventas es WhatsApp Cloud API oficial de Meta.
La IA actual es Google Gemini.
El backend usa servicios Python/FastAPI.
El frontend usa Next.js.

## Estado actual

- Fases 1-11: completadas
- Fase 12: Platform Console pendiente
- Versión live: https://commerce-ops-web.onrender.com

## Stack actual del proyecto

Verificar siempre en `package.json`, `requirements.txt`, `render.yaml` y configuración real antes de asumir compatibilidad o versiones.

- Frontend: Next.js 14.2.35 + React 18 + TypeScript 5
- UI: TailwindCSS 3.3 + shadcn/ui
- Backend: Python 3.11 + FastAPI 0.128.8
- DB/Auth: Supabase PostgreSQL + RLS + Auth + Realtime
- Storage: Supabase Storage
- IA: Google Gemini (`google-genai==1.47.0`, modelo actual `gemini-2.5-flash`)
- WhatsApp: WhatsApp Cloud API oficial
- Shipping: Envia API
- Marketplace: Mercado Libre OAuth 2.0
- Hosting: Render

## Principios críticos del proyecto

- Multi-tenant desde el día 1.
- Toda entidad sensible debe tener `tenant_id`.
- RLS es obligatorio y es la barrera final de seguridad.
- El frontend no es una barrera de seguridad.
- El API/Gateway valida antes de llegar a DB cuando aplique.
- Nada crítico depende del LLM como fuente de verdad.
- Stock, precios, pedidos, permisos y estados operativos salen de DB y servicios internos.
- Solo herramientas oficiales para WhatsApp.
- Toda integración externa debe estar desacoplada del núcleo.
- Cambios importantes deben ser auditables.

## Reglas críticas de implementación

### Seguridad

1. En Server Components usar `getUser()`, no `getSession()` como garantía de validación.
2. Toda operación sensible debe revalidar identidad, tenant y rol.
3. Nunca confiar en datos de tenant/role enviados por cliente.
4. Service-role keys solo en backend/controlado, nunca expuestas al cliente.
5. Secretos y credenciales nunca deben escribirse en el repo.

### Multi-tenant

6. Toda tabla operativa relevante debe incluir `tenant_id`.
7. Toda query debe respetar el aislamiento por tenant.
8. Subdominio o UI separada no reemplazan seguridad en DB.
9. RLS y RBAC son obligatorios; filtros en frontend no cuentan como aislamiento real.

### Frontend

10. Server Components para carga inicial de datos.
11. Client Components para interactividad.
12. Mutaciones deben revalidar permisos y contexto de tenant.
13. Revalidar caché o paths después de mutaciones exitosas cuando aplique.

### IA

14. Gemini no decide verdad transaccional.
15. La knowledge base no reemplaza datos operativos.
16. Si una respuesta depende de datos vivos, consultarlos desde herramientas o backend.
17. RAG con pgvector está previsto, pero debe tratarse como capacidad controlada, no como autoridad.

### WhatsApp

18. Solo WhatsApp Cloud API oficial.
19. El flujo base es: webhook -> persistencia -> procesamiento -> respuesta.
20. Cualquier límite, template, media capability o política debe validarse en documentación oficial vigente antes de implementarse.

## Arquitectura Funcional y Navegación

> **IMPORTANTE**: La fuente de verdad innegociable del árbol de módulos, navegación, consolas y dominios reside en `.context/00-product.md` (Fase 0 dictada).
> NO confíes en agrupaciones de código pre-restructuración. Antes de proponer crear o mover un módulo, lee obligatoriamente `.context/00-product.md`.


## Estructura de directorios clave

```text
apps/web/
  app/dashboard/
  components/ui/
  utils/supabase/

services/
  api/
  connector-whatsapp/
  ai-orchestrator/
```
