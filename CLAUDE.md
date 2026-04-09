# CLAUDE.md

## Propósito del workspace

Este workspace corresponde exclusivamente al proyecto **Commerce Ops Platform**.

Toda acción debe orientarse a mantener, clarificar y evolucionar este sistema con enfoque de:

- producción real
- arquitectura modular
- seguridad multi-tenant
- trazabilidad documental estricta
- consistencia entre producto, frontend, backend, integraciones e infraestructura

Este repositorio no debe ser tratado como demo, experimento o MVP improvisado.

---

## Fuente de verdad del proyecto

La fuente de verdad persistente del proyecto es el **repositorio**.

Orden de prioridad para reconstrucción de contexto:

1. Código implementado
2. `AGENTS.md`
3. `docs/HANDOFF.md`
4. `docs/**`
5. Este archivo `CLAUDE.md`

Si detectas contradicciones entre código y documentación, debes:

1. identificarlas explícitamente
2. evaluar cuál fuente es más reciente y confiable
3. proponer la corrección
4. actualizar los `.md` correspondientes
5. dejar rastro documental del cambio

No inventar implementaciones no presentes en código o documentación.  
Si algo no está claro, debes marcarlo como **no confirmado**.

---

## Mandato operativo permanente

Esta máquina está dedicada a pruebas y trabajo exclusivo de este proyecto.

Tienes autorización para intervenir técnicamente en el workspace cuando sea necesario para avanzar correctamente, incluyendo:

- crear, mover, actualizar o eliminar archivos del proyecto
- reorganizar carpetas del repositorio si mejora claridad y mantenibilidad
- instalar, actualizar o remover dependencias y herramientas necesarias
- usar `dnf`, `rpm`, `pip`, `python`, `node`, `npm`, `pnpm`, `uv`, `git` u otras herramientas del entorno cuando se justifique técnicamente
- corregir estructura, scripts, configuración y convenciones del proyecto
- consolidar duplicidades técnicas o documentales

Aun con esa autorización:

- no ejecutar acciones destructivas irreversibles sin explicarlas antes de forma explícita
- no realizar cambios de alcance funcional visible sin validar antes el impacto en producto
- no asumir que algo está correcto solo porque compila o existe
- no tratar archivos vacíos o parciales como si fueran módulos completos

---

## Regla obligatoria de documentación oficial vigente

Ninguna decisión técnica, instalación, actualización, eliminación, configuración, integración o cambio arquitectónico debe realizarse sin revisión previa de documentación oficial vigente de la tecnología correspondiente.

Esto aplica especialmente a:

- Claude Code / `CLAUDE.md`
- Next.js / React / TypeScript / Tailwind
- Supabase
- Render
- FastAPI
- Meta / WhatsApp
- Mercado Libre
- Telegram
- Envia / Courier / Shipping APIs

Antes de tocar cualquier cosa, debes:

1. identificar qué documentación oficial aplica
2. resumir la acción a realizar
3. indicar riesgos
4. indicar si requiere intervención humana o no

Toda intervención humana debe informarse de manera:

- clara
- explícita
- paso a paso
- dummy-friendly
- basada en documentación oficial vigente

---

## Reglas obligatorias de documentación del repositorio

Todo cambio importante debe quedar reflejado en la documentación del repositorio.

Es obligatorio:

- mantener muy actualizados los archivos `.md`
- sincronizar código, arquitectura, roadmap, riesgos y estado real
- documentar decisiones nuevas o cambios de criterio
- dejar trazabilidad de deuda técnica, contradicciones y validaciones pendientes
- evitar que el contexto crítico quede solo en el chat

Después de cada bloque importante de trabajo debes:

1. resumir qué cambiaste
2. listar archivos modificados
3. explicar por qué lo cambiaste
4. indicar qué documentación oficial sustentó la decisión
5. actualizar los `.md` necesarios
6. señalar riesgos o validaciones pendientes

---

## Definición del producto a preservar

Este proyecto corresponde a una **plataforma SaaS multi-tenant de operaciones e-commerce conversacionales**.

La plataforma debe centralizar, de forma modular y segura:

- catálogo
- variantes
- media
- inventario
- pedidos
- conversaciones por WhatsApp
- knowledge base
- integraciones por tenant
- métricas
- auditoría
- operación interna
- shipping / courier
- futura expansión a más canales

### Regla conceptual crítica

El producto **no es un bot**.

El producto es un **centro de operaciones e-commerce conversacional** donde:

- WhatsApp es el canal principal con el cliente
- el inventario, catálogo, pedidos y reglas viven en el core
- el LLM es una capa de asistencia controlada
- las integraciones son módulos desacoplados
- el tenant opera su negocio desde una consola propia
- el dueño de la plataforma opera el SaaS desde una consola separada

---

## Stack inicial vigente del proyecto

Debes asumir como stack inicial vigente (no mandatorio), salvo que el código o la documentación indiquen claramente otra cosa:

### Frontend inicial

- Next.js / React
- TypeScript
- Tailwind CSS
- componentes UI reutilizables en `apps/web/components/ui` y/o `packages/ui`
- utilidades SSR/Auth de Supabase

### Backend inicial

- Python
- FastAPI
- Supabase Postgres
- RLS + RBAC
- WhatsApp connector
- AI orchestrator
- connector framework para futuras integraciones

### Infraestructura inicial

- Render
- Supabase

Esto debe tratarse como **baseline vigente**, no como decisión eterna e inmutable.

---

## Restricciones arquitectónicas obligatorias

No romper:

- modelo multi-tenant
- aislamiento por tenant
- RLS
- RBAC
- Supabase como source of truth operativa
- arquitectura modular
- separación entre frontend, backend, workers e integraciones
- cumplimiento oficial de Meta / WhatsApp

No usar el LLM como fuente de verdad de:

- stock
- precios
- pedidos
- shipping quotes
- tracking
- estados transaccionales
- permisos
- sincronización de inventario

No proponer soluciones no oficiales para WhatsApp.

No permitir que conectores externos se conviertan en la fuente maestra del negocio.

---

## Superficies administrativas obligatorias

Debes asumir y preservar que existen dos superficies administrativas distintas.

### 1. Tenant Console

Interfaz para el cliente/tenant que compra la plataforma.

Debe operar su negocio y no debe exponérsele información de plataforma global ni de otros tenants.

### 2. Platform Console

Interfaz para el dueño de la plataforma, superadmin y soporte interno.

Debe operar el SaaS, no una tienda específica, salvo accesos de soporte debidamente auditados.

### Regla crítica

No mezclar ambas superficies en una sola navegación caótica.

Debe existir separación clara de:

- layout
- navegación
- permisos
- visibilidad
- casos de uso
- responsabilidades

---

## Alcance funcional y visual que debes respetar

### Módulos base de la Tenant Console

Tomar como baseline funcional/documental:

- Inicio / Dashboard
- Inbox / Conversaciones
- Catálogo
- Media
- Inventario
- Pedidos
- Contactos
- Knowledge Base
- Integraciones
- Shipping / Courier
- Métricas
- Auditoría
- Configuración

### Módulos base de la Platform Console

Tomar como baseline funcional/documental:

- Overview global
- Tenants
- Tenant detail
- Health Center
- Integraciones globales
- Jobs / Queue Ops
- Seguridad
- Auditoría global
- Billing / planes
- Feature flags
- Soporte operativo

### Regla de alcance

No crear, eliminar, fusionar, renombrar ni expandir módulos visibles del producto sin antes:

1. identificar la situación actual en código y docs
2. justificar el cambio
3. indicar impacto funcional y técnico
4. documentarlo
5. marcar si requiere validación humana

---

## Shipping / Courier como capacidad formal del producto

Debes tratar Courier / Shipping como una capacidad formal del producto, no como detalle marginal.

### Diseño funcional esperado

Debe contemplarse documentalmente:

- cotización de envíos desde la interfaz del tenant
- uso de la cotización dentro de pedidos y operación
- soporte de recogida / pickup
- futura capacidad para label, tracking, manifest y webhook
- historial de cotizaciones y acciones
- intervención humana cuando haga falta
- uso desde WhatsApp solo a través del backend y conectores reales

### Regla crítica

El sistema puede responder cotizaciones o estados de envío por WhatsApp solo si:

- existen datos mínimos válidos
- el backend puede consultar el conector real
- la respuesta se basa en datos transaccionales reales
- no se inventa información

Si faltan datos, debe:

- solicitar los datos faltantes
- o escalar a humano

### Acoplamiento prohibido

No acoplar Shipping directamente al LLM.  
Toda cotización, pickup, label o tracking debe modelarse como responsabilidad del backend / conector correspondiente.

---

## Reglas sobre interfaz y frontend

La UI actual del repositorio debe tratarse como **base parcial**, no como definición final cerrada del producto.

No debes asumir que la estructura actual de `apps/web/app/**` representa el producto completo.

### Sí puedes hacer sin aprobación previa

- refactor técnico interno sin impacto funcional visible
- mover componentes a una estructura más mantenible
- consolidar duplicados
- corregir naming
- mejorar organización de `packages/`
- corregir inconsistencias entre implementación y documentación
- endurecer validaciones
- mejorar scripts y tooling
- documentar gaps de interfaz y estado real

### Debes proponer antes de ejecutar

- nuevas pantallas
- cambios de navegación
- eliminación de módulos visibles
- rediseño funcional del panel
- ampliaciones visibles no documentadas
- cambios de experiencia del tenant
- cambios de experiencia del superadmin

### Si detectas gaps funcionales o UI faltante

No implementarlos automáticamente.

Debes:

1. documentar el gap
2. indicar evidencia en código/docs
3. explicar impacto técnico y de producto
4. proponer opciones
5. marcarlo como pendiente de validación humana

---

## Regla de orden de trabajo

El orden correcto de trabajo es:

### 1. Claridad funcional y visual

Primero dejar claro documentalmente:

- qué producto se construye
- qué consolas existen
- qué módulos tiene cada una
- qué está implementado
- qué es parcial
- qué está pendiente
- qué stack inicial lo sostiene

### 2. Alineación arquitectura ↔ frontend ↔ backend

Después documentar:

- qué backend requiere cada módulo visual
- qué endpoints existen
- qué endpoints faltan
- qué tablas ya soportan cada módulo
- qué políticas RLS aplican
- qué workers o procesos async hacen falta

### 3. Implementación técnica

Solo después avanzar en cambios de frontend o backend con menor ambigüedad.

### Regla crítica

Primero claridad funcional/visual.  
Después backend correspondiente.  
No al revés.

---

## Tipos de cambio y nivel de autonomía

### Puede ejecutar sin aprobación previa

- consolidación de estructura técnica
- eliminación de duplicidad técnica claramente obsoleta
- corrección documental
- refactor interno sin impacto visible
- mejora de scripts, build, configuración y organización
- endurecimiento de seguridad
- corrección de inconsistencias entre código y `.md`
- creación de nuevos archivos Markdown necesarios
- consolidación de Markdown redundante si se preserva trazabilidad

### Debe proponer antes de ejecutar

- cambios de alcance funcional
- decisiones de roadmap con impacto material
- cambios visibles de interfaz
- nuevas integraciones no planificadas
- cambios de contrato entre módulos
- migraciones con impacto funcional o de datos no trivial
- eliminación de archivos no Markdown importantes

### Requieren intervención humana obligatoria

- Meta Business / WhatsApp Business Platform
- credenciales y tokens
- DNS
- dominios
- cuentas de proveedores
- suscripción/configuración de webhooks externos
- activación/validación final de canales
- pruebas E2E que requieren acción fuera del workspace

---

## Gestión de inconsistencias y duplicidades

Si detectas duplicidad, deuda técnica, estructura obsoleta o archivos contradictorios, debes:

1. identificarlo
2. proponer corrección
3. actualizar la documentación correspondiente
4. consolidar si es seguro hacerlo
5. dejar claramente documentado:
   - qué se consolidó
   - qué se mantuvo
   - qué se eliminó
   - por qué

No eliminar archivos Markdown útiles sin haber consolidado antes su contenido relevante.

---

## Archivos de contexto que debes mantener especialmente vivos

Debes prestar especial atención a mantener alineados:

- `./AGENTS.md`
- `./README.md`
- `./docs/HANDOFF.md`
- `./docs/product/overview.md`
- `./docs/product/scope.md`
- `./docs/product/current-scope.md`
- `./docs/product/personas-and-consoles.md`
- `./docs/product/admin-ui-modules.md`
- `./docs/product/navigation-map.md`
- `./docs/architecture/overview.md`
- `./docs/architecture/modules.md`
- `./docs/architecture/front-back-separation.md`
- `./docs/integrations/whatsapp.md`
- `./docs/integrations/mercadolibre.md`
- `./docs/integrations/telegram.md`
- `./docs/integrations/courier-envia.md`
- `./docs/roadmap/implementation-phases.md`
- `./docs/research/official-doc-checklist.md`
- `./docs/risks/risk-register.md`

Si alguno no existe y es necesario para sostener contexto, debes crearlo.

---

## Prioridades inmediatas del workspace

La prioridad actual del workspace es:

1. clarificar y gobernar el contexto persistente del repo
2. dejar explícita la intención visual y funcional de la interfaz
3. separar claramente Tenant Console y Platform Console
4. documentar el stack inicial vigente de frontend, backend e infraestructura
5. integrar Courier / Shipping con Envia a nivel documental/arquitectónico (https://docs.envia.com/docs/getting-started)
6. dejar claro que después de definir bien la interfaz se aborda el backend correspondiente
7. resolver inconsistencias documentales y duplicidades
8. proponer el siguiente paso técnico más seguro

No expandir funcionalidad visible del producto hasta cerrar ese contexto.

---

## Formato mínimo esperado en cada respuesta de trabajo

Toda respuesta debe incluir:

- Resumen
- Decisiones
- Riesgos
- Impacto técnico
- Archivos que deben actualizarse
- Siguiente paso recomendado

Si hubo cambios, además debes:

- listar archivos creados/modificados/eliminados
- indicar evidencia en código/docs
- indicar documentación oficial revisada
- dejar pendientes claros

---

## Criterio final

Trabaja con criterio técnico fuerte, disciplina documental estricta y trazabilidad total.

El repositorio debe quedar preparado para que cualquier sesión futura entienda sin ambigüedad:

- qué producto se está construyendo
- cómo debe verse
- qué consolas existen
- qué módulos tiene cada consola
- cómo entra Courier / Shipping con Envia
- qué stack inicial lo sostiene
- y que después de definir bien la interfaz se aborda el backend correspondiente
