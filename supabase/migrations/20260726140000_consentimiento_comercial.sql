-- ═══════════════════════════════════════════════════════════════════════════
-- Consentimiento COMERCIAL, separado del transaccional.
--
-- EL PROBLEMA
-- El recordatorio de carrito abandonado —un HSM de categoría MARKETING con 10% de
-- descuento— se autorizaba con `contacts.consent_given`, que es el consentimiento
-- de Habeas Data que el cliente da para que se procese su pedido.
--
-- Ley 2300 de 2023 art. 5 par. 2 (verificado 2026-07-26): los mensajes comerciales
-- "no pueden ser obligatorios al momento de la transacción", el consentimiento debe
-- ser **explícito** para el uso comercial de la base de datos, y hay que ofrecer un
-- "mecanismo ágil, sencillo y eficiente" para darse de baja.
--
-- Es decir: aceptar que traten tus datos para venderte lo que pediste NO es aceptar
-- que te manden publicidad. Usar el mismo campo para las dos cosas es exactamente
-- lo que la norma prohíbe.
--
-- POR QUÉ ESTA MIGRACIÓN NO "ACTIVA" NADA
-- Las columnas nacen en NULL a propósito. El gate de comunicaciones
-- (lib/outbound_gate.py) exige consentimiento comercial explícito para cualquier
-- mensaje de esa categoría, así que hasta que exista un flujo real de opt-in
-- —donde el cliente diga que sí, separado de la compra— el marketing simplemente
-- no sale. Fail-closed: preferimos no mandar a mandar sin derecho.
--
-- No hay backfill desde `consent_given`. Convertir un consentimiento transaccional
-- en comercial sería justo el acto que la norma prohíbe, y hacerlo en una migración
-- lo dejaría además sin rastro de cuándo y cómo se obtuvo.
-- ═══════════════════════════════════════════════════════════════════════════

ALTER TABLE public.contacts
    ADD COLUMN IF NOT EXISTS consent_comercial_at         TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS consent_comercial_revoked_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS consent_comercial_fuente     TEXT;

COMMENT ON COLUMN public.contacts.consent_comercial_at IS
    'Cuándo el titular aceptó EXPLÍCITAMENTE recibir comunicaciones comerciales. '
    'Distinto de consent_given (Habeas Data transaccional): Ley 2300 art. 5 par. 2 '
    'prohíbe que el mensaje comercial sea obligatorio al momento de la transacción. '
    'NULL = no hay consentimiento comercial y no se le puede escribir con ese fin.';
COMMENT ON COLUMN public.contacts.consent_comercial_fuente IS
    'Cómo se obtuvo: la norma exige que sea explícito, así que hay que poder demostrar '
    'de dónde salió (p. ej. "respondio_SI_a_opt_in", "formulario_web").';

-- El barrido de marketing pregunta "¿quién tiene consentimiento comercial vigente?".
CREATE INDEX IF NOT EXISTS idx_contacts_consent_comercial
    ON public.contacts (tenant_id)
    WHERE consent_comercial_at IS NOT NULL AND consent_comercial_revoked_at IS NULL;


-- ── Quién puede recibir un mensaje comercial ────────────────────────────────

CREATE OR REPLACE FUNCTION public.tiene_consentimiento_comercial(
    p_contact_id UUID,
    p_tenant_id  UUID
)
RETURNS BOOLEAN
LANGUAGE sql
STABLE
SET search_path = public, pg_temp
AS $$
    SELECT COALESCE((
        SELECT c.consent_comercial_at IS NOT NULL
           AND c.consent_comercial_revoked_at IS NULL
           -- Revocar el consentimiento de Habeas Data revoca TODO: no tendría sentido
           -- seguir mandándole publicidad a quien pidió que no lo contactemos más.
           AND c.consent_revoked_at IS NULL
        FROM public.contacts c
        WHERE c.id = p_contact_id AND c.tenant_id = p_tenant_id
    ), false);
$$;

COMMENT ON FUNCTION public.tiene_consentimiento_comercial(UUID, UUID) IS
    'Fail-closed: sin fila, sin consentimiento explícito, o con Habeas Data revocado, '
    'devuelve false. Ley 2300 art. 5 par. 2.';

REVOKE ALL ON FUNCTION public.tiene_consentimiento_comercial(UUID, UUID) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.tiene_consentimiento_comercial(UUID, UUID) FROM anon;
GRANT EXECUTE ON FUNCTION public.tiene_consentimiento_comercial(UUID, UUID) TO authenticated;
GRANT EXECUTE ON FUNCTION public.tiene_consentimiento_comercial(UUID, UUID) TO service_role;
