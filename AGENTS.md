# Workspace AI Guidelines — Konvi Platform

**Leer siempre antes de tocar código o documentación.**

---

## Qué es este producto

SaaS multi-tenant de operaciones e-commerce conversacionales vía WhatsApp (B2B2C, foco Colombia).
El LLM (Gemini) es asistencia controlada — nunca fuente de verdad de datos transaccionales.

## Dónde está la fuente de verdad

| Qué buscar | Dónde |
|---|---|
| Tree funcional, dominios, qué es módulo | `.context/00-product.md` ← **OBLIGATORIO leer primero** |
| Estado de implementación real | `.context/01-state.md` |
| Stack con versiones reales | `.context/02-stack.md` |
| Reglas de implementación | `.context/03-rules.md` |
| Próximos pasos y deuda | `.context/04-next-steps.md` |
| Política documental | `.context/05-doc-policy.md` |
| Infra, credenciales, lecciones | `docs/HANDOFF.md` |
| Arquitectura técnica | `docs/architecture/` |
| Integraciones | `docs/integrations/` |
| Reglas técnicas expandidas | `.agents/rules/` |
| Workflows de implementación | `.agents/workflows/` |

---

## Estado Actual del Sistema

**Fases 1-11.5 ✅ completadas** (incl. Reclamos, Compras, Finanzas, Marketplace). Fase 12 ❌ pendiente (bloqueante: OQ-P01).

Ver estado detallado por módulo → `.context/01-state.md`
Ver servicios live e infra → `docs/HANDOFF.md`

## Reglas Obligatorias para AI Agents

1. **Documentación Oficial**: No asumas endpoints, scopes ni capacidades. Valida en docs oficiales siempre.
2. **Políticas de Meta**: Todo diseño conforme a WhatsApp Cloud API Anti-Spam y políticas de mensaje.
3. **No Magia LLM**: El LLM nunca es fuente de verdad para stock, precios, pedidos, permisos ni estados.
4. **Multi-Tenant Real**: Cada operación debe estar atada a `tenant_id` y filtrada por RLS en Postgres.
5. **No MVP / Demo**: Diseñar para producción real. Sin atajos de seguridad ni hardcodes de tenant.
6. **Seguridad en capas**: RLS es la última barrera. El API Gateway es la barrera previa. El frontend no es seguridad.
7. **Tree primero**: Antes de crear o mover un módulo, leer `.context/00-product.md`.
8. **Platform Console fuera de alcance**: No diseñar, expandir ni implementar Platform Console en esta iniciativa.

---

## Stack — Versiones Reales

> Verificar siempre en `apps/web/package.json` y `services/*/requirements.txt`.

| Capa | Versión real |
|---|---|
| Frontend | Next.js **14.2.35** + React ^18 + TypeScript ^5 |
| UI | TailwindCSS ^3.3.0 + shadcn/ui (11 componentes en `apps/web/components/ui/`) |
| Backend | Python **3.11.13** + FastAPI 0.128.8 |
| DB / Auth | Supabase (PostgreSQL + RLS + Auth + Realtime) |
| IA | `google-genai==1.47.0` — modelo `gemini-2.5-flash` |
| Mensajería | WhatsApp Cloud API (Meta oficial v21.0) |
| Shipping | Envia API (Fase Inicial — quote + historial live) |
| Hosting | Render — Free plan (4 servicios live) — ver upgrade path en `docs/deployment/render-upgrade-path.md` |

---

## Fases de Implementación

| Fases | Estado |
|---|---|
| 1-11.5 | ✅ Completadas |
| 12 (Platform Console) | ❌ Bloqueada — OQ-P01 sin resolver — fuera de alcance actual |
| 13 (Shopify) | ❌ Futuro lejano |

---

## Herramientas en VM (sin venv)

```bash
supabase db query --linked -f archivo.sql   # psql TCP bloqueado por Supavisor
python3.11 main.py                          # usar python3.11 explícito en esta VM
pnpm --filter web dev                       # Node v20.20.2 via nvm
```

---

## Seguridad Git

- `.env` **NUNCA** al repositorio. Config en Render Environment Variables.
- `node_modules/`, `.venv/`, `.next/` están en `.gitignore`.
- Rama activa: `develop` → `origin/develop`
