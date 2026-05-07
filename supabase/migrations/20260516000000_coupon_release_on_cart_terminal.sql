-- =============================================================================
-- Coupon redemption auto-release on cart terminal — Sem 6 I.2.9 (rev. 105)
-- Fecha: 2026-05-07
-- ADR: docs/adr/0015-coupon-engine.md (D8: cupón liberado si orden cancelada)
--
-- Trigger DB que pasa coupon_redemptions.status='applied' → 'revoked'
-- automáticamente cuando un conversation_cart transiciona a estado
-- terminal ('cancelled' / 'abandoned').
--
-- Razón arquitectónica: la transición cart → terminal puede ocurrir desde
-- múltiples servicios (worker cron futuro de TTL, agente humano via UI
-- Inbox, lógica de cancelación manual). Usar trigger DB garantiza
-- consistencia atómica sin depender de cada caller recordar invocar
-- revoke_coupon().
--
-- redemptions_count NO se incrementa (D5: solo en APPROVED), por lo que
-- esta liberación es net-zero — el cupón queda disponible para otros
-- usos hasta su límite real.
-- =============================================================================

CREATE OR REPLACE FUNCTION public.tg_release_coupon_on_cart_terminal()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    -- Solo actuar en transición A → terminal, no en updates noop.
    IF NEW.status IN ('cancelled', 'abandoned')
       AND (OLD.status IS NULL OR OLD.status NOT IN ('cancelled', 'abandoned')) THEN

        UPDATE public.coupon_redemptions
        SET status         = 'revoked',
            revoked_at     = NOW(),
            revoked_reason = 'cart_' || NEW.status
        WHERE cart_id = NEW.id
          AND status  = 'applied';

    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS release_coupon_on_cart_terminal
    ON public.conversation_carts;

CREATE TRIGGER release_coupon_on_cart_terminal
    AFTER UPDATE OF status ON public.conversation_carts
    FOR EACH ROW
    EXECUTE FUNCTION public.tg_release_coupon_on_cart_terminal();

COMMENT ON FUNCTION public.tg_release_coupon_on_cart_terminal IS
'ADR-0015 D8: revoca redemptions ''applied'' automáticamente cuando cart
pasa a cancelled/abandoned. Atomic; cubre todos los call-sites cross-service.';
