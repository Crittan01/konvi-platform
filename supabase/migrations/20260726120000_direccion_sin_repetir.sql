-- ═══════════════════════════════════════════════════════════════════════════
-- La dirección del vendedor no debe repetir la misma palabra dos veces.
--
-- En DIVIPOLA hay municipios cuyo nombre es idéntico al de su departamento —
-- Bogotá D.C. es el caso obvio, pero también San Andrés, y varias capitales
-- comparten nombre con el suyo. El armado concatenaba calle, ciudad,
-- departamento y país sin mirar, y producía:
--
--     Calle 123 # 45-67, Bogotá D.C., Bogotá D.C., Colombia
--
-- En un comprobante eso se lee como un error de la plataforma, no como un dato.
-- Se eliminan los tramos consecutivos repetidos, comparando sin tildes ni
-- mayúsculas para que "Bogota D.C." y "Bogotá D.C." cuenten como el mismo.
--
-- La normalización va con `translate` inline y NO con la extensión `unaccent`:
-- no está instalada y no vale agregar una extensión al esquema por una mejora de
-- presentación. Con el desplegable DIVIPOLA los valores ya vienen idénticos byte
-- a byte; quitar tildes es la defensa para los datos viejos escritos a mano.
-- ═══════════════════════════════════════════════════════════════════════════

CREATE OR REPLACE FUNCTION public.tenant_seller_identity(p_tenant_id UUID)
RETURNS JSONB
LANGUAGE sql
STABLE
SET search_path = public, pg_temp
AS $$
    WITH t AS (
        SELECT
            NULLIF(trim(tn.razon_social), '')            AS razon_social,
            NULLIF(trim(tn.name), '')                    AS nombre_comercial,
            NULLIF(trim(tn.doc_tipo), '')                AS doc_tipo,
            COALESCE(NULLIF(trim(tn.doc_numero), ''),
                     NULLIF(trim(tn.nit), ''))           AS doc_numero,
            NULLIF(trim(tn.doc_dv), '')                  AS doc_dv,
            NULLIF(trim(tn.tipo_persona), '')            AS tipo_persona,
            NULLIF(trim(tn.regimen_iva), '')             AS regimen_iva,
            NULLIF(trim(tn.domicilio_direccion), '')     AS calle,
            NULLIF(trim(tn.domicilio_ciudad), '')        AS ciudad,
            NULLIF(trim(tn.domicilio_departamento), '')  AS depto,
            CASE upper(NULLIF(trim(tn.domicilio_pais), ''))
                WHEN 'CO' THEN 'Colombia'
                ELSE NULLIF(trim(tn.domicilio_pais), '')
            END                                          AS pais,
            NULLIF(trim(tn.email_contacto), '')          AS email,
            NULLIF(trim(tn.email_habeas_data), '')       AS email_habeas_data
        FROM public.tenants tn
        WHERE tn.id = p_tenant_id
    ),
    partes AS (
        -- Tramos en orden, ya sin los ausentes.
        SELECT t.*, ARRAY(
            SELECT x FROM unnest(ARRAY[t.calle, t.ciudad, t.depto, t.pais]) WITH ORDINALITY AS u(x, n)
             WHERE x IS NOT NULL ORDER BY n
        ) AS tramos
        FROM t
    ),
    direccion AS (
        SELECT p.*, (
            SELECT string_agg(x, ', ' ORDER BY n)
            FROM (
                SELECT x, n,
                       -- Compara contra el tramo ANTERIOR, sin tildes ni mayúsculas.
                       lag(translate(lower(x),
                           'áàäâéèëêíìïîóòöôúùüûñ',
                           'aaaaeeeeiiiioooouuuun')) OVER (ORDER BY n) AS previo_norm,
                       translate(lower(x),
                           'áàäâéèëêíìïîóòöôúùüûñ',
                           'aaaaeeeeiiiioooouuuun') AS norm
                FROM unnest(p.tramos) WITH ORDINALITY AS u(x, n)
            ) s
            WHERE previo_norm IS DISTINCT FROM norm
        ) AS direccion_texto
        FROM partes p
    ),
    calc AS (
        SELECT
            COALESCE(d.razon_social, d.nombre_comercial) AS nombre,
            CASE WHEN d.doc_numero IS NULL THEN NULL
                 WHEN d.doc_dv IS NULL THEN COALESCE(d.doc_tipo,'NIT') || ' ' || d.doc_numero
                 ELSE COALESCE(d.doc_tipo,'NIT') || ' ' || d.doc_numero || '-' || d.doc_dv
            END AS documento,
            -- Sin calle ni ciudad no hay dirección de notificación judicial.
            CASE WHEN d.calle IS NULL AND d.ciudad IS NULL THEN NULL
                 ELSE d.direccion_texto END AS direccion,
            d.email, d.email_habeas_data, d.tipo_persona, d.regimen_iva,
            (d.razon_social IS NULL AND d.nombre_comercial IS NOT NULL) AS usa_nombre_comercial
        FROM direccion d
    )
    SELECT jsonb_strip_nulls(jsonb_build_object(
        'nombre',       c.nombre,
        'documento',    c.documento,
        'direccion',    c.direccion,
        'email',        c.email,
        'tipo_persona', c.tipo_persona,
        'regimen_iva',  c.regimen_iva,
        'email_habeas_data', c.email_habeas_data
    )) || jsonb_build_object(
        'usa_nombre_comercial', COALESCE(c.usa_nombre_comercial, false),
        'completa', (c.nombre IS NOT NULL AND c.documento IS NOT NULL
                     AND c.direccion IS NOT NULL AND c.email IS NOT NULL),
        'faltantes', ARRAY(
            SELECT x FROM unnest(ARRAY[
                CASE WHEN c.nombre    IS NULL THEN 'razón social o nombre' END,
                CASE WHEN c.documento IS NULL THEN 'NIT o documento de identidad' END,
                CASE WHEN c.direccion IS NULL THEN 'dirección de notificación judicial' END,
                CASE WHEN c.email     IS NULL THEN 'correo de contacto' END
            ]) x WHERE x IS NOT NULL)
    )
    FROM calc c;
$$;
