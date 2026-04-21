# @commerce/db — Snapshot legacy de migraciones

Última actualización: 2026-04-21

## Advertencia crítica

`supabase/migrations/` es la única fuente canónica del esquema.

Este paquete contiene un snapshot parcial/histórico y **no** debe usarse como referencia de estado real.

## Estado de sincronización real

| Fuente | Archivos |
|---|---:|
| `supabase/migrations/` (canónica) | 42 |
| `packages/db/migrations/` (snapshot) | 19 |
| Faltantes en snapshot legacy | 28 |

Además, este paquete conserva mirrors legacy `00001..00005` que no forman parte del naming canónico vigente.

## Regla operativa

Para aplicar cambios de esquema:

```bash
supabase db query --linked -f supabase/migrations/<archivo>.sql
```

## Decisión vigente

Mantener `packages/db` como referencia histórica mínima hasta definir una estrategia formal (por ejemplo, tipos generados o tooling DB compartido).
