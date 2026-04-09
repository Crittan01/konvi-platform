# Integración Telegram Bot

Última actualización: 2026-04-09

---

## Estado

❌ **Pendiente — Fase 8+**

No existe implementación. Canal reservado para uso interno operacional.

---

## Propósito

Telegram como **canal interno de la plataforma** para:
- Alertas operacionales del sistema (errores, health, cold starts)
- Notificaciones a operadores de un tenant (nuevo pedido, conversación escalada, etc.)
- Comandos internos para soporte técnico (no exposición al cliente final)

**Telegram NO es un canal de atención al cliente** en este producto.
El canal de atención al cliente es WhatsApp.

---

## Casos de uso previstos

| Caso | Destinatario | Trigger |
|------|-------------|---------|
| Error crítico en AI Orchestrator | DevOps/Superadmin | Exception en worker loop |
| Nuevo mensaje pendiente de human takeover | Agente del tenant | `conversations.status = human_takeover` |
| Token Meta próximo a expirar | Superadmin | Verificación periódica |
| Cold start detectado en servicio | DevOps | Health check fallido |
| Nueva orden recibida de MeLi | Manager del tenant | IPN de MeLi procesado |
| Error de sincronización de catálogo | Manager del tenant | Error en connector MeLi |

---

## Diseño técnico (pendiente)

- Bot de Telegram por plataforma (no por tenant en la versión inicial)
- Posiblemente un bot por tenant en versiones avanzadas
- API: Telegram Bot API oficial (`https://core.telegram.org/bots/api`)
- Canal de alertas configurado como chat ID en env vars

---

## Variables de entorno requeridas (diseño)

```
TELEGRAM_BOT_TOKEN=...    ← Token del bot (BotFather)
TELEGRAM_ALERT_CHAT_ID=...  ← Chat ID del canal de alertas internos
```

---

## Reglas

- No enviar datos confidenciales de tenants por Telegram (solo alertas y resúmenes)
- No usar Telegram como canal de atención al cliente
- No implementar antes de tener el ciclo WhatsApp completamente estable

---

## Documentos relacionados

- `docs/architecture/connector-framework.md` — Framework de conectores
- `docs/operations/support-model.md` — Modelo de soporte interno
- `docs/roadmap/implementation-phases.md` — Roadmap
