-- F6 (auditoría 2026-07-02) — audit-trail Habeas Data en el path agéntico (Ley 1581/2012).
-- Autorizado explícitamente por el founder.
--
-- Los gates del bot (dispatcher) para solicitudes de derechos ("borren mis datos", "retiro mi
-- consentimiento") y para menores autodeclarados (Decreto 1377 Art. 7) escalan a humano + notifican,
-- pero NO dejaban registro en consent_audit_log — el registro canónico append-only para la SIC. El
-- enum de eventos no tenía un valor apropiado para estas dos situaciones. Se añaden:
--   - 'data_rights_request': el titular pidió ejercer derechos (acceso / supresión / portabilidad /
--     rectificación) por texto libre; el DSR lo tramita un asesor (data_subject_request).
--   - 'minor_detected': el titular declaró/sugirió ser menor → tratamiento detenido pendiente de
--     autorización del representante legal.
--
-- Aditivo (widen del CHECK): las filas existentes lo satisfacen y el código viejo sigue insertando el
-- subset anterior → seguro de aplicar antes del deploy del código que inserta los nuevos valores.

ALTER TABLE public.consent_audit_log
    DROP CONSTRAINT IF EXISTS consent_audit_log_event_check;

ALTER TABLE public.consent_audit_log
    ADD CONSTRAINT consent_audit_log_event_check
    CHECK (event IN (
        'granted',
        'revoked',
        'rectified',
        'export_request',
        'portability',
        'pii_access',
        'deleted',
        'purged',
        'data_rights_request',
        'minor_detected'
    ));

COMMENT ON CONSTRAINT consent_audit_log_event_check ON public.consent_audit_log IS
    'Eventos válidos del ciclo de vida del consent + solicitudes Habeas Data. F6 2026-07-02 añade '
    '''data_rights_request'' (DSR detectado por el bot) y ''minor_detected'' (Decreto 1377 Art. 7) '
    'para completar el paper-trail Ley 1581 del canal agéntico.';
