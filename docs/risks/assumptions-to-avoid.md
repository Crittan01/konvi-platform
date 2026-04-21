# Suposiciones a Evitar

Última actualización: 2026-04-21

| Suposición | Realidad |
|---|---|
| El frontend es seguridad | No. La seguridad vive en API + DB + filtros tenant |
| RLS basta con `service_role` | No. `service_role` exige scoping explícito |
| El LLM puede resolver verdad transaccional | No. Solo backend y DB son fuente de verdad |
| Render Free es suficiente para producción real | No necesariamente. validar trigger de upgrade |
| Documentación vieja todavía aplica | No. prevalece `.context/01-state.md` + `docs/HANDOFF.md` + código |
