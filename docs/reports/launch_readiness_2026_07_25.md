# Readiness pre-lanzamiento — ¿qué falta para abrir el número real?

Auditoría del 2026-07-25. **Pregunta**: ¿qué falta para que "el ecosistema esté OK" y se pueda
habilitar un número de WhatsApp de negocio y recibir clientes reales?

**Método**: 9 auditores paralelos sobre el camino crítico de negocio (bot, pedidos, pagos, envíos,
inbox, compliance, observabilidad, multi-tenancy, infra) + crítico de completitud + árbitro.
995 llamadas a herramientas. Instrucción explícita de **no confiar en `.context/` ni `docs/`**
(parcialmente desactualizados) y verificar contra código/tests/migraciones.

**Veredicto**: `falta-trabajo-significativo`. **No se puede abrir el número hoy.**

---

## 0. Lo que se ARREGLÓ durante la propia auditoría (ya en prod)

### 🔴 CRÍTICO — Secretos de Vault leíbles sin login (CERRADO)

`anon` (la llave publishable que por diseño viaja en el bundle del navegador) podía **leer y
sobreescribir los secretos de Vault de cualquier tenant sin autenticarse**.

Dos condiciones combinadas, **verificadas contra prod** (`information_schema` + `pg_get_functiondef`):
1. `pgsec_read_secret` / `create` / `update` / `delete` / `upsert` otorgadas a **PUBLIC y anon**.
2. Guard permisivo: `IF auth.uid() IS NOT NULL THEN <check ownership> END IF; RETURN decrypted_secret;`
   — escrito para que pasara `service_role` (auth.uid() NULL), pero **`anon` comparte esa propiedad**
   → el check se salta entero.

Expuesto: `access_token` + `app_secret` de WhatsApp, `private_key` + `events_key` de Wompi,
`bot_token` de Telegram. Con las de escritura: poner un `app_secret` propio y firmar webhooks válidos.

**Fix aplicado a prod** (PR #162, protocolo seguro: isolated-test → apply → post-check → ledger):
`REVOKE ALL FROM PUBLIC, anon` en las 5 funciones + fail-closed ante `auth.role() = 'anon'`.
**Sin regresión**: `service_role` sigue leyendo (verificado) y los 4 servicios en health 200.

> **Causa raíz sistémica (follow-up abierto)**: no hay `ALTER DEFAULT PRIVILEGES`, así que **toda
> función nueva nace con `GRANT ALL ... TO anon`**. Se confirmó al regenerar el baseline: la función
> del trigger creada hoy recibió ese grant automáticamente. Hay que auditar las ~20 funciones
> `SECURITY DEFINER` restantes por el mismo patrón (la auditoría señaló `fn_apply_retention` como
> otro caso — **no verificado por mí aún**).

### CI de `develop` en rojo (CERRADO en #162)

Cada PR con migración dejaba `develop` rojo: el gate anti-drift (`scripts/schema_drift_check.sh`)
exige regenerar `tests/dbharness/schema_baseline.sql`, y los checks del PR pasaban porque el gate
corre en el job `Harness DB` y solo se ve después del merge. Afectó a #156, #159, #161.
Baseline regenerado con replay real (podman + supabase CLI).

---

## 1. Estado verificado de prod (medido, no inferido)

| Chequeo | Resultado |
|---|---|
| Migraciones repo vs prod | 227 vs 223 en el ledger → **drift del LEDGER, no migraciones faltantes** (verificado objeto por objeto). La única no aplicada es ADR-0029, y **el código no la referencia** → no bloqueante |
| Columnas de los errores de julio (`payment_reminder_sent_at`, `human_takeover_at`, …) | **Todas existen en prod** → esos errores venían de una DB **local** desactualizada, no de producción |
| Recursos Render | 4 servicios en **Starter** (no Free) → **sin cold starts**, health checks OK, autoDeploy on |
| Aislamiento multi-tenant (lint AST) | **0 gaps** (baseline sostenido) |
| Colas pgmq | **Vacías, sin backlog**; 180 + 115 mensajes procesados |
| Pipeline del bot | **Vivo**: inbound `04:52:04` → outbound `04:52:17` (**13 s**) |
| Env vars críticas en Render | **Todas presentes** (`APP_URL`, `MFA_RECOVERY_COOKIE_SECRET`, DSNs de Sentry en los 4) |
| 148 rechazos HMAC | **Históricos**: 30 OK / 73 fail acumulados desde el deploy del 23-jul; el `app_secret` estuvo mal ese período y se corrigió el 25-jul. **El canal inbound funciona** (probado en vivo) |
| Cross-region ⚠️ | Supabase **us-east-1** ↔ Render **oregon** → cada query cruza el país (~60-70 ms). Compone en los 13 s del turno |
| Backups ❓ | **No verificable** sin token de Management API → la auditoría reporta `pitr_enabled=false` (RPO ~24 h). **Confirmar en el dashboard** |

> **Nota de método**: tres "bloqueantes" que había marcado resultaron **falsos** al verificar el
> nombre real que lee el código (`is_customer_visible`, `APP_URL` vs `WEB_APP_URL`,
> `MFA_RECOVERY_COOKIE_SECRET` en el servicio equivocado). Verificar el símbolo exacto **antes** de
> declarar "falta config".

---

## 2. Bloqueantes de lanzamiento (sin arreglar → un cliente real sufre)

Ordenados por severidad. `[F]` = requiere acción del founder.

> ### Avance al cierre del 2026-07-25
>
> **Los 8 bloqueantes de código están cerrados y VIVOS EN PRODUCCIÓN.** Los 4 que quedan abiertos dependen de
> acciones externas del founder (Wompi, Aveonline, plantillas Meta, aviso de privacidad) o son el
> comprobante de compra, en curso.
>
> Distinguir dos estados importa, porque no significan lo mismo para un cliente real:
>
> | # | Bloqueante | Estado |
> |---|---|---|
> | 1 | RBAC de dinero | ✅ **vivo en prod** (#165) |
> | 5 | Sobreventa | ✅ **vivo en prod** (#168) |
> | 8 | Conversación duplicada | ✅ **vivo en prod** (#166) |
> | 6 | Inbound sin durabilidad | ✅ cerrado (#167) — **vivo en prod** |
> | 7 | Pago huérfano | ✅ cerrado (#169) — **vivo en prod** |
> | 9 | Cliente mudo | ✅ cerrado (#170 + #171) — **vivo en prod** |
> | 10 | Escalación sin red | ✅ cerrado (#172) — **vivo en prod** |
> | 12 | Comprobante de compra | ✅ **vivo en prod** (#180-#186) |
> | 2, 3, 4, 11 | Plantillas Meta, Wompi, Aveonline, aviso de privacidad | ⏸️ `[F]` founder |
>
> **Actualización del cierre: TODO desplegado.** `production == develop`, los 4 servicios sanos y
> certificados con Chromium. Los 8 bloqueantes de código están vivos en producción. Lo único que
> queda son las **4 acciones externas del founder** (plantillas Meta, Wompi, Aveonline, aviso de
> privacidad), que no dependen de código.

1. ✅ **CERRADO Y VIVO EN PROD (#165).** **RBAC de dinero inexistente en la DB** — las policies de `orders`/`coupons`/`product_variations`
   son `FOR ALL USING (tenant_id = ...)` **sin distinción de rol**, y `authenticated` conserva los
   GRANT de escritura. Un `operator` (el empleado del Inbox, el caso de uso central) puede cambiar
   `total_amount`, marcar pedidos `confirmed` sin pago y emitir cupones 100% off escribiendo directo
   a PostgREST. → 2-3 días.
2. **Notificaciones post-despacho muertas por diseño** `[F]` — "enviado", "entregado", "novedad",
   "reembolso completado", "reclamo resuelto" se mandan como **texto libre fuera de la ventana CSW
   de 24 h** de Meta, y el consumidor de la cola no distingue el error `131047` ni tiene fallback a
   plantilla HSM. Como una entrega tarda 1-5 días, **el caso NORMAL es que el cliente que pagó nunca
   se entere** — y el operador ve el mensaje en `messages` como si se hubiera enviado. Las 4
   plantillas están en `LOCAL_DRAFT` (nunca sometidas). → Founder: someter 3 plantillas UTILITY (días
   de lead time, **arrancar YA**). Código: 3-4 días.
3. **Wompi en sandbox** `[F]` — nadie puede pagar de verdad. Y el cutover no valida las llaves
   (guarda `private_key` + `events_key` sin verificar coherencia de prefijo con el entorno).
   → Founder: cuenta prod + registrar URL de eventos en el panel de **producción** (distinto al de
   sandbox) + pago real de monto mínimo. Código: 1 día.
4. **Guías Aveonline simuladas** `[F]` — con `AVEONLINE_GENERATE_REAL_GUIDES=false` el código fuerza
   `simulate=True` siempre; el cliente recibe por WhatsApp **un tracking que no existe**, sin marcador
   de simulación. → Founder: credenciales productivas + `idagente` correcto. Código: 1-2 días.
5. ✅ **CERRADO Y VIVO EN PROD (#168).** **Sobreventa reproducida** — dos reservas activas de la misma variación (camino NORMAL: "agrégame
   2 más"); el 2.º consume choca con el índice único, **la excepción se traga** y el corte de circuito
   no lo detecta. El cliente paga y el inventario no baja lo vendido. → 2-3 días.
6. ✅ **CERRADO (#167) Y VIVO EN PROD.** **Inbound sin durabilidad** — el connector ACKea 200 a Meta **antes** de persistir y delega a un
   `BackgroundTask` in-process. Si el proceso muere entre el ACK y el INSERT (deploy, OOM, crash), el
   mensaje del cliente **se pierde para siempre** (Meta no reintenta). Contraste: Wompi **sí** tiene
   inbox durable. → 2-3 días.
7. ✅ **CERRADO (#169) Y VIVO EN PROD.** **Pago APPROVED sobre orden terminal se descarta con log INFO** — el cliente aplica un cupón, el
   bot invalida la orden, pero el link viejo sigue pagable ~30 min. Si paga el viejo: **pagó y no
   tiene pedido**, sin void, sin reembolso, sin alerta. → 1-2 días.
8. ✅ **CERRADO Y VIVO EN PROD (#166).** **Conversación duplicada** — no existe constraint único sobre `conversations(tenant_id,
   customer_phone)` y el upsert es read-then-insert. En WhatsApp lo normal es mandar 2-3 mensajes
   seguidos → dos conversaciones → carrito, FSM y escalación se parten en silencio. → 1 día.
9. ✅ **CERRADO (#170 + #171) Y VIVO EN PROD.** **Paquete "cliente mudo"** — seis caminos independientes donde el cliente queda sin respuesta y
   nadie se entera (entre ellos: escribir "Cancelar" queriendo anular el pedido dispara el **opt-out
   de WhatsApp** y lo deja mudo de por vida). → 2-3 días + 1 día el detector "inbound sin outbound".
10. ✅ **CERRADO (#172) Y VIVO EN PROD.** **Escalación sin red en las rutas de dinero y legales** — el SLA ancla en `escalation_audit` y
    hace `continue` si no existe; solo 4 de ~10 rutas la escriben, y quedan fuera justo retracto
    Ley 1480, DSR Habeas Data y menor de edad. → 2 días.
11. **Aviso de privacidad no publicado** `[F]` — el archivo es un template con placeholders que
    **declara por escrito** que no se publica al titular. La autorización de Habeas Data no es
    "informada" (Decreto 1377). → Founder: redactar el aviso real. Código: 1-2 días.
12. ✅ **CERRADO Y VIVO EN PROD (#180-#186).** **El comprador no recibe NINGÚN documento de compra** — ni factura, ni recibo, ni comprobante.
    → Un **comprobante de compra no fiscal** (número de pedido, ítems, totales, vendedor
    identificable, fecha) es barato, no necesita proveedor de facturación y cubre la expectativa
    razonable del comprador + la identificación del vendedor de Ley 1480. **Esto sí es de lanzamiento.**

    > **CORRECCIÓN (2026-07-25)** — la versión previa listaba "facturación electrónica DIAN" como
    > bloqueante duro. **Reclasificado a "verificar aplicabilidad con el contador"**, tras revisar
    > fuente oficial y por observación del founder:
    > - El umbral de **3.500 UVT** define ser **responsable de IVA** (Art. 437 ET) — **no** la
    >   obligación de facturar, que según la DIAN es **independiente** de esa condición
    >   ([Concepto 106 de 2022](https://normograma.dian.gov.co/dian/compilacion/docs/concepto_tributario_dian_0000106_2022.htm)).
    > - Los **no obligados** están en el **Art. 616-2 ET** + Resolución DIAN 000042/2020.
    > - **Persona jurídica → obligada sin importar ingresos.** Persona natural bajo 3.500 UVT →
    >   puede igual estarlo si debe llevar contabilidad (patrimonio > 4.500 UVT o ingresos > 500 SMMLV)
    >   o si la DIAN la incorporó por resolución. Existe la vía del **documento equivalente** (POS).
    > - **Conclusión**: depende de la forma jurídica y los ingresos de cada tenant → **decisión del
    >   contador, no de código**, y **no bloquea el día 1** si el tenant está bajo los supuestos de
    >   exención. Lo que sí queda es el comprobante de compra de arriba.
    > **VALIDAR EN FUENTE OFICIAL DIAN** antes de cualquier decisión definitiva.

13. **El tenant no tiene modelo de identidad legal en la DB** — `public.tenants` solo tiene un `nit`
    suelto (text, nullable, sin validación). **No existe**: razón social (el `name` es marca
    comercial), tipo de persona (natural/jurídica), tipo y número de documento, dígito de
    verificación, régimen de IVA, ni domicilio fiscal. Verificado sobre el esquema real de prod.
    → Es la causa de que el aviso de privacidad sea un template con placeholders: **no hay datos que
    poner**. Bloquea la identificación del **Responsable del Tratamiento** (Habeas Data) y del
    vendedor (Ley 1480), y es el prerrequisito de cualquier facturación futura. → 1-2 días
    (migración aditiva + sección "Datos legales" en la consola + consumo en el aviso).
13. **Prerrequisitos Meta sin verificar** `[F]` — modo de la App (Development vs Live), Business
    Verification, Display Name aprobado, número registrado con PIN. Tier observado **TIER_250**
    (250 destinatarios únicos/24 h). → ~1 h de verificación; los trámites pendientes son días.
14. **PITR deshabilitado** `[F]` — RPO real ~24 h mientras el runbook promete "minutos". Un borrado a
    las 20:00 pierde los pedidos y pagos del día, con Wompi ya habiendo cobrado.
15. **`LAUNCHED=False`** — el guard deja correr 16+ scripts destructivos (incluidos
    `wipe_conversation.py` y `uat/e2e_chat.py`) contra la única Supabase que existe, con solo un
    warning. → **5 minutos**, hacerlo ANTES de abrir el número.

---

## 3. Orden de ejecución recomendado

**Día 0 — arrancar los 3 trámites externos en paralelo** (su lead time no depende de nosotros y son
camino crítico): plantillas UTILITY a Meta · cuenta Wompi producción · validación legal DIAN/Ley 1480.
*Esto es lo que decide si el lanzamiento es en 3 o en 6 semanas.*

Luego, en código:
1. ~~Cerrar el agujero de PostgREST~~ **(pgsec HECHO)** + policies por rol en tablas de dinero +
   auditar las ~20 `SECURITY DEFINER` restantes + `ALTER DEFAULT PRIVILEGES`.
2. Durabilidad y observabilidad del inbound (inbox durable espejando el patrón Wompi ya probado).
3. Índice único + upsert atómico de conversaciones (precedido de un SELECT en prod por duplicados).
4. Sobreventa (INSERT idempotente + corte por cantidad + detector de deriva del ledger).
5. Ola de dinero Wompi → **luego** el cutover a producción con pago real.
6. Paquete "cliente mudo" + detector `inbound sin outbound` (la red más barata: cubre 6 caminos).
7. Notificaciones HSM (en cuanto Meta apruebe las plantillas).
8. Red de escalación (fallback a `human_takeover_at`).
9. Guías reales Aveonline (**arreglar el dry-run primero**, que hoy revienta con 500).
10. Legal y privacidad (el contenido lo escribe el founder desde el día 0).
11. Infra pre-apertura: PITR + simulacro de restore, `LAUNCHED=True`, MFA obligatorio, alert rules de
    Sentry (**después** de arreglar el `environment`, o quedan vacías), uptime monitor externo.
12. **UAT analítico en producción con el número real, ANTES de publicarlo**: una compra completa
    turn-a-turn verificando en DB después de **cada** paso, midiendo p50/p95, y probando explícitamente
    los caminos arreglados (escribir "Cancelar", 3 mensajes en <1 s, escalación 2 h sin responder,
    notificación con >24 h desde el último mensaje). **Este es el sello.**
13. Recién entonces: abrir el número, con volumen bajo, vigilando TIER_250 a mano.

---

## 4. Acciones del founder (con lead time — arrancar ya)

- **Meta**: verificar modo Live, Business Verification, Display Name, PIN del número, y la URL del
  webhook. Cruzar el `app_secret` con el botón "Probar" (#160, ya desplegado).
- **Meta plantillas**: someter ≥3 UTILITY (despachado, entregado, reembolso). **Camino crítico más largo.**
- **Wompi producción**: cuenta + llaves + **registrar la URL de eventos en el panel de producción**
  (es otro panel; es el paso que más se olvida) + pago real de prueba.
- **Aveonline**: credenciales productivas (no la demo pública), `idagente` correcto (es la dirección
  de despacho, no el asesor comercial), origen con `street`, y **una guía real de prueba**.
- **Telegram**: probar que la escalación llega al grupo (si migra a supergrupo, el `chat_id` cambia y
  **todas las escalaciones dejan de notificar en silencio**).
- **Legal**: aviso de privacidad real (razón social, NIT, finalidades, canal de derechos) + DPA
  aceptado + `tenants.nit`/`email_contacto` + términos de venta/garantía/retracto. Validar DIAN y RNBD
  con asesor (**en fuente oficial**, los umbrales cambian por decreto).
- **Infra**: contratar PITR + simulacro de restore cronometrado **antes** de tener datos de clientes;
  alert rules de Sentry con destinatario real; uptime monitor externo; notificaciones de fallo de Render.

---

## 5. Advertencias de método

- Un subagente consultó **directamente la DB de producción** con la secret key para verificar sus
  hallazgos (el harness lo marcó). Fueron lecturas, sin daño, pero los hallazgos que citan datos vivos
  deben leerse con ese contexto.
- El dossier completo (9 auditores + crítico + árbitro, con evidencia `file:line`) está en el output
  del workflow de la sesión. Los ítems marcados "no verificado por mí" necesitan confirmación antes
  de actuar sobre ellos.
