import os

base_dir = "/home/ansible/workspaces/commerce-ops-platform"

files = {
    ".agents/rules/01-global-behavior.md": """# Global Behavior Rule
Siempre trabaja como un agente técnico experto enfocado en construir un producto SaaS multi-tenant B2B2C.
1. No usar endpoints, scopes o caps sin consultar docs oficiales.
2. Prioriza multi-tenant real, RLS, RBAC.
""",
    ".agents/rules/02-architecture-stack.md": """# Architecture & Stack Rule
- Frontend: React + TypeScript + Tailwind + shadcn/ui
- Backend: Python + FastAPI
- DB/Auth/etc: Supabase
- Hosting: Render
Valida antes de implementar.
""",
    ".agents/rules/03-security-tenant.md": """# Security & Multi-Tenant Rule
Todo debe ser multi-tenant usando identificador `tenant_id` atado al usuario.
Filtra todo vía Row Level Security (RLS) en Postgres.
No usar frontend como capa única de seguridad.
""",
    ".agents/rules/04-whatsapp-meta-policies.md": """# WhatsApp & Meta Policies Rule
1. Cíñete a las guías de WhatsApp Cloud API.
2. No uses herramientas no oficiales para WA.
3. El Opt-in y las políticas anti-spam deben ser el centro de la validación.
""",
    ".agents/workflows/architecture-blueprint.md": """---
description: Blueprint para definir arquitectura
---
# Flujo de Blueprint de Arquitectura

1. **Objetivo:** Definir una pieza de arquitectura antes del código libre.
2. **Entradas:** Requisitos del usuario y docs oficiales.
3. **Pasos:** Investigar -> Validar en docs -> Escribir plan -> Aprobar -> Ejecutar.
4. **Intervención:** Humano debe aprobar límites y scopes.
""",
    ".agents/workflows/integration-research.md": """---
description: Proceso de validación de integraciones de 3eros
---
# Validación de Integraciones

1. Leer la Documentación oficial sobre Rate limits y Auth type.
2. Comprobar Webhooks expuestos y garantías de entrega.
""",
    ".agents/workflows/feature-implementation.md": """---
description: Proceso guiado para la implementación de un Feature
---
1. Escribir plan usando planning mode.
2. Crear archivo de test plan.
3. Ejecutar y testear.
""",
    ".agents/workflows/deployment-readiness.md": """---
description: Verificaciones previas al despliegue
---
Verificar secretos, variables de entorno y runbooks actuales.
""",
    ".agents/workflows/security-review.md": """---
description: Audits de RLS y accesos
---
Chequeo de RLS, JWT, custom claims, y exposición de service role.
""",
    ".agents/workflows/monorepo-bootstrap.md": "--- \ndescription: Monorepo Setup \n---\nSetup turborepo o pnpm workspaces.",
    ".agents/workflows/module-bootstrap.md": "--- \ndescription: Create Module \n---\nGenerar modulo con linting y test configurado.",
    ".agents/workflows/docs-sync-review.md": "--- \ndescription: ValidarDocs \n---\nVerificiar si los docs base están unificados.",

    "docs/product/overview.md": "# Product Overview\nPlataforma B2B para operaciones conversacionales B2B2C e-commerce, incluyendo WA, Telegram, ML.",
    "docs/product/scope.md": "# Scope\nIncluye: Backoffice, WA inbox, gestión de catálogo (MercadoLibre sync), cotización de envíos, RAG AI.",
    "docs/product/functional-requirements.md": "# Functional Requirements\n- Interacción humana requerida en setup de WABA\n- Backoffice CRUD\n- AI generation para respuestas",
    "docs/product/non-functional-requirements.md": "# Non-Functional Requirements\n- HA 99.9%, Multi-tenant isolated (RLS), GDPR/CCPA readiness.",
    "docs/architecture/overview.md": "# Tech Stack\nReact/TS Frontend. FastAPI Backend. Supabase (Postgres, Storage, Auth, RLS). Render Deploy.",
    "docs/architecture/modules.md": "# Modulos\nWeb, Admin Portal (Opcional, colapsado en Web por ahora para simplicidad), API, Workers (Render), Connectores.",
    "docs/architecture/multi-tenant-security.md": "# RLS & Auth\nDiseño para Custom Claims para perfiles (Admin, Agent, Manager) y `tenant_id` RLS en BD.",
    "docs/architecture/connector-framework.md": "# Connector AI\nFramework modular para inyectar Mercado Libre, WhatsApp, y Shopify como módulos independientes que exponen un standar.",
    "docs/architecture/realtime.md": "# Real-time\nSupabase Real-time websockets (inbox).",
    "docs/architecture/async-processing.md": "# Queues\npgmq / Supabase queues / Redis para tareas largas.",
    "docs/architecture/output-template.md": "# Salida\nDecisiones deben generar este template de riesgos y doc validada.",
    "docs/ai/orchestrator.md": "# Orchestrator\nGemini API routing para intenciones y calling commands estructurados.",
    "docs/ai/tool-contracts.md": "# Tools Base\nBúsqueda Catálogo, Chequeo Stock, Envío Plantilla WA.",
    "docs/ai/rag.md": "# RAG\nArchivos PDF incrustados vía pgvector.",
    "docs/ai/guardrails.md": "# Guardrails\nRestricciones: La IA no puede confirmar compras sin token de pasarela. No asume stock no devuelto por BBDD.",
    "docs/data/schema.md": "# Esquema Inicial\nUsers, Tenants, Products, Variations, Orders, Messages.",
    "docs/data/rls-policies.md": "# RLS Policies\n`auth.uid() = user_id` y claims `tenant_id` check por toda tabla.",
    "docs/data/tenant-isolation.md": "# Aislamiento de Inquilino\nUn solo esquema Postgres; separación lógica (row-level).",
    "docs/data/indexes.md": "# Índices\nUUID y FKs.",
    "docs/data/audit-model.md": "# Auditoría\nPostgres Trigger logic para history de cambios críticos.",
    "docs/integrations/whatsapp.md": "# WhatsApp Cloud API\nTokens, Webhooks, plantillas de interacción requerida.",
    "docs/integrations/telegram.md": "# Telegram Bot\nOp. Internas. Comandos.",
    "docs/integrations/mercadolibre.md": "# ML Integration\nAuth global, sync de publicaciones.",
    "docs/integrations/shopify-prep.md": "# Shopify (Futuro)\nGraphQL Admin.",
    "docs/integrations/custom-store-prep.md": "# Custom Store\nAPIs abiertas para e-commerce propios.",
    "docs/deployment/environments.md": "# Entornos\nStaging (Render PRs) & Production.",
    "docs/deployment/render-supabase.md": "# Red & Despliegue\nFastAPI a Render. Web a Vercel/Render. BD en Supabase Platform.",
    "docs/deployment/secrets-and-config.md": "# Secrets\n1Password / Doppler / Supabase Vault.",
    "docs/deployment/domains-and-subdomains.md": "# Dominios\nWildcard `*.app.com` si se requiere para tenants, o un subpath.",
    "docs/deployment/rollout-and-rollback.md": "# Rollback\nPostgres migrations down-steps.",
    "docs/operations/human-interventions.md": "# Human Interventions\n* INTERVENCIÓN HUMANA REQUERIDA:\n- Meta Business WABA creation (Dueño negocio).\n- Conectar Meli Mapps (Dueño).\n- Cambiar Plan Render (DevOps).",
    "docs/operations/runbooks.md": "# Runbooks\nRestart Workers, Reset Env Var.",
    "docs/operations/onboarding-tenants.md": "# Onboarding \nSelf-serve con invitación.",
    "docs/operations/support-model.md": "# Support\nTelegram to agent.",
    "docs/research/official-doc-checklist.md": "# Official Doc Checklist\n[ ] Validar límites de rate de WA.\n[ ] Webhooks Supabase retry model.\n[ ] Gemini Tool calling limites.",
    "docs/research/validated-decisions.md": "# Validados\nNinguna hasta verificar hoy.",
    "docs/research/pending-validations.md": "# Pendientes de Verificación\n- Soporte MCP en Workspace.\n- Compatibilidad de claims custom en RLS de Supabase.",
    "docs/roadmap/implementation-phases.md": "# Fases\n1. Base Monorepo. 2. Auth y RLS. 3. Backoffice Web y CRUD básico. 4. Integracion ML. 5. Inbox WA.",
    "docs/roadmap/milestones.md": "# Milestones\nAlpha (Interno), Beta (Meli sync), RC (WA act).",
    "docs/risks/open-questions.md": "# Open Questions\n¿Costo por token IA por mes?",
    "docs/risks/risk-register.md": "# Riesgos\nBaneo WA por policies Meta.",
    "docs/risks/assumptions-to-avoid.md": "# Assumptions\nNo asumir que se puede enviar MKT masivo por WA sin penalidad.",
    
    "docs/research/mcp-and-skills.md": """# Entendiendo MCP y Skills en Antigravity
**MCP (Model Context Protocol)**: Un estándar para proporcionar contexto de forma controlada a asistentes de IA desde fuentes externas (archivos locales, herramientas, bases de datos, APIs).

**Skills en Antigravity**: Carpetas con instrucciones, scripts o contexto almacenados usualmente en `.agents/skills`. Estos configuran capacidades extendidas, como rutinas complejas o manejo de stacks específicos. Se activan/apoyan leyendo los MD locales (ej. `SKILL.md`).

**Gemini Docs MCP**: Proveedor MCP que permite buscar y añadir contexto oficial en tiempo de conversación, reduciendo alucinaciones al preguntar "¿Cómo implemento X en Supabase?". 

Debes comprobar en el chat y el entorno si están configurados antes de utilizarlos activamente. Un fallback es buscar en la web vía \`search_web\`.
""",

    "AGENTS.md": """# Workspace AI Guidelines

Este repositorio es la matriz de producto SaaS Conversacional Multi Tenant.

## Reglas Obligatorias:
1. **Documentación Oficial**: No asumas, valida SIEMPRE.
2. **Políticas de Meta**: Diseño conforme a WhatsApp Cloud API Anti-Spam.
3. **No Mágia LLM**: No uses IA como base de datos.
4. **Verificar MCP/Skills**: No asumas que están habilitados.

Leer `.agents/rules/` antes de tocar código.
""",
    "README.md": """# Commerce Ops Platform
Plataforma SaaS Multi-Tenant para operación e-commerce y WhatsApp.
Ver `AGENTS.md` para reglas de AI y desarrollo.
""",
    ".env.example": """# Entorno Base
SUPABASE_URL=
SUPABASE_ANON_KEY=
SUPABASE_SERVICE_ROLE_KEY=
META_WA_TOKEN=
TELEGRAM_BOT_TOKEN=
MELI_APP_ID=
""",
    "package.json": """{
  "name": "commerce-ops-platform",
  "version": "1.0.0",
  "private": true,
  "workspaces": [
    "apps/*",
    "packages/*",
    "services/*"
  ]
}
""",
    "pnpm-workspace.yaml": """packages:
  - 'apps/*'
  - 'packages/*'
  - 'services/*'
"""
}

for filepath, content in files.items():
    full_path = os.path.join(base_dir, filepath)
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(content.strip() + "\\n")
    print("Created:", full_path)
