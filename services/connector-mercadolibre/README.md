# services/connector-mercadolibre — PLACEHOLDER VACÍO

**Estado**: Directorio vacío. No hay implementación aquí.

## Dónde vive la integración MeLi real

La integración con Mercado Libre está implementada **dentro de `services/api/`**:

```
services/api/
├── routers/marketplace.py      — endpoints REST (listings, link, import, sync)
├── routers/meli_webhook.py     — IPN webhook handler
├── routers/integrations.py     — OAuth 2.0 flow
└── integrations/meli_client.py — cliente HTTP MeLi API
```

Ver documentación completa en `docs/integrations/mercadolibre.md`.

## Propósito futuro de este directorio

Si en el futuro se decide extraer MeLi como servicio independiente (para escalado separado,
rate limiting independiente, o múltiples cuentas de plataforma), el código de `services/api/`
se movería aquí y se agregaría como quinto servicio en `render.yaml`.

**No implementar nada aquí sin una decisión arquitectónica formal.**
Este directorio NO está en `render.yaml` y no se despliega.
