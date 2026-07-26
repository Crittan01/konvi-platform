-- ═══════════════════════════════════════════════════════════════════════════
-- Higiene: quitar de PUBLIC/anon las funciones de TRIGGER.
--
-- ESTO NO ES UNA VULNERABILIDAD, y conviene dejarlo escrito para que nadie
-- vuelva a gastar tiempo investigándolo. Verificado empíricamente contra prod:
--
--     BEGIN; SET LOCAL ROLE anon;
--     SELECT public.trg_void_receipt_on_cancel();
--     → ERROR: trigger functions can only be called as triggers
--
-- Postgres rechaza invocar directamente cualquier función que devuelva `trigger`,
-- así que el EXECUTE sobre ellas es inerte, tenga quien lo tenga.
--
-- POR QUÉ IGUAL SE LIMPIA: 28 de 32 funciones de trigger figuraban ejecutables
-- por `anon`. Cualquier auditoría que pregunte "¿qué puede ejecutar la llave
-- pública del navegador?" —y hoy se hicieron varias— recibe 28 falsos positivos
-- que hay que descartar uno por uno. La consulta debe poder responderse de un
-- vistazo, porque el día que aparezca un positivo REAL tiene que destacarse.
--
-- De paso cierra el hueco de #164, que solo recorrió las SECURITY DEFINER: las
-- funciones de trigger sin `prosecdef` quedaron fuera de aquel barrido.
-- ═══════════════════════════════════════════════════════════════════════════

DO $$
DECLARE
    fn RECORD;
    n INT := 0;
BEGIN
    FOR fn IN
        SELECT p.oid::regprocedure AS sig
        FROM pg_proc p
        JOIN pg_namespace ns ON ns.oid = p.pronamespace
        WHERE ns.nspname = 'public'
          AND p.prorettype = 'trigger'::regtype
          AND (has_function_privilege('anon', p.oid, 'EXECUTE')
               OR has_function_privilege('authenticated', p.oid, 'EXECUTE'))
    LOOP
        EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC', fn.sig);
        EXECUTE format('REVOKE ALL ON FUNCTION %s FROM anon', fn.sig);
        EXECUTE format('REVOKE ALL ON FUNCTION %s FROM authenticated', fn.sig);
        n := n + 1;
    END LOOP;
    RAISE NOTICE 'Funciones de trigger retiradas de PUBLIC/anon/authenticated: %', n;
END
$$;

-- Los triggers siguen disparando igual: se ejecutan con los privilegios del
-- propietario de la tabla, NO con los de quien hizo el INSERT/UPDATE. Quitar el
-- EXECUTE a los roles de cliente no puede romperlos — y las pruebas del harness,
-- que dependen de varios de estos triggers, lo confirman.
