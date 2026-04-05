# Multi-Tenant Security

## Objetivo
Garantizar separación real entre clientes y protección exhaustiva física ante consumo desmedido de cuotas (Noisy Neighbor).

## Mecanismos obligatorios de Aislamiento
- `tenant_id` obligatorio en todas las entidades persistentes.
- **Validación de Storage Quotas**: Políticas de Supabase RLS resuelven el acceso de las filas, pero NO limitan el volumen en Bytes por usuario en bucket primitivo. Se exige una validación proxy externa. La tabla `storage_usage_stats` rastreará el bucket. El Frontend FastAPI backend validará este consumo previo a emitir una URL `presigned upload`.
- **JWT Custom Claims**: Roles inyectados por metadata de sesión. El backend evalúa claims inyectados.
- Auditoría restrictiva por trigger relacional.

## Patrón Arquitectónico Base 
```sql
CREATE POLICY "Tenants isolation" ON sensitive_table
FOR SELECT USING (
  tenant_id = (auth.jwt() ->> 'tenant_id')::uuid 
  OR (auth.jwt() ->> 'user_role') = 'platform_admin'
);
```

## Reglas de Arquitectura Resolutiva
1. El frontend nunca sube libremente un Blob. Todo archivo cruza por la validación del API de FastAPI backend.
2. El subdominio en la URL pública es una feature de UX, no de seguridad.
3. RLS es la capa que previene filtrado cruzado de filas; Middlewares de Rate-Limit en FastAPI previenen abusos comerciales y DDOS.