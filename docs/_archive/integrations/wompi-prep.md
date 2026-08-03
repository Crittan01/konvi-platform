> **⚠️ ARCHIVADO — 2026-08-02.** Prep superada: la integración Wompi está implementada y live; la referencia vigente es `docs/integrations/wompi.md`. Conservado solo como registro histórico.

---

# Wompi Prep (Sandbox -> Produccion)

Ultima actualizacion: 2026-04-21
Estado: preparacion documental (integracion runtime aun no implementada)

Este documento define el alistamiento para Wompi sin forzar implementacion anticipada.

## DECISION FINAL

No implementar Wompi en runtime en esta fase.
Preparar llaves, ambientes y playbook operativo para activar en Fase C de Inbox.

## VALIDAR EN DOCUMENTACION OFICIAL

- Inicio rapido: https://docs.wompi.co/docs/colombia/inicio-rapido/
- Ambientes y llaves: https://docs.wompi.co/docs/colombia/ambientes-y-llaves/
- Eventos: https://docs.wompi.co/docs/colombia/eventos/
- Tokens de aceptacion: https://docs.wompi.co/docs/colombia/tokens-de-aceptacion/
- Transacciones: https://docs.wompi.co/docs/colombia/transacciones/

## RIESGO

- Mezclar sandbox y produccion por configuracion incorrecta de llaves o URL de eventos.
- Confirmar pago por canal conversacional sin validacion transaccional server-side.
- Exponer llaves privadas/eventos en canales inseguros.

## IMPACTO OPERATIVO

- Permite arrancar integracion mas rapido cuando cierre Fase B.
- Reduce riesgo de errores de ambiente y de cumplimiento legal.
- Alinea pagos con gobierno multi-tenant existente.

## INTERVENCION HUMANA REQUERIDA

**INTERVENCION HUMANA REQUERIDA**: Si
**RESPONSABLE**: Owner del comercio + DevOps
**MOMENTO**: cierre de Fase B y antes de iniciar implementacion tecnica Wompi
**PASOS DUMMY O GUIADOS**:
1. Entrar a dashboard de Wompi (`comercios.wompi.co`).
2. Ir a `Desarrollo -> Programadores`.
3. Registrar y custodiar llaves de ambos ambientes:
   - Sandbox: `pub_test_*`, `prv_test_*`, `test_events_*`, `test_integrity_*`
   - Produccion: `pub_prod_*`, `prv_prod_*`, `prod_events_*`, `prod_integrity_*`
4. Configurar URL de eventos por ambiente (dos URLs separadas).
5. Entregar llaves por canal seguro a DevOps para carga en secretos.
**INSUMOS NECESARIOS**: acceso owner a dashboard Wompi + secret manager corporativo
**CRITERIO DE EXITO**: llaves y eventos por ambiente validados, sin mezcla sandbox/prod

## Convencion recomendada de secretos (preparacion)

Nota: estos nombres son propuestos para futura implementacion. No forman parte aun del contrato runtime actual.

- `WOMPI_PUBLIC_KEY_SANDBOX`
- `WOMPI_PRIVATE_KEY_SANDBOX`
- `WOMPI_EVENTS_KEY_SANDBOX`
- `WOMPI_INTEGRITY_KEY_SANDBOX`
- `WOMPI_PUBLIC_KEY_PROD`
- `WOMPI_PRIVATE_KEY_PROD`
- `WOMPI_EVENTS_KEY_PROD`
- `WOMPI_INTEGRITY_KEY_PROD`
- `WOMPI_ENV` (`sandbox` o `production`)
- `WOMPI_EVENTS_URL_SANDBOX`
- `WOMPI_EVENTS_URL_PROD`

## Reglas de seguridad

1. Nunca guardar llaves reales en `.env.example` ni en docs.
2. Nunca exponer llaves privadas en frontend.
3. Confirmaciones de pago solo desde backend, nunca desde mensaje de usuario.
4. Cualquier evento webhook debe verificarse por firma/checksum segun documentacion oficial.

## Go / No-Go para iniciar implementacion tecnica

GO:
1. Fase A y B de Inbox cerradas y certificadas.
2. Playbook de llaves/eventos ejecutado en sandbox.
3. Criterios legales (aceptacion de contratos) confirmados.

NO-GO:
1. Sin UAT estable de intents transaccionales.
2. Sin separacion estricta de ambientes.
3. Sin owner funcional para conciliacion de pagos.
