# UAT Inbox - Fase A (Catalogo y Variantes)

Ultima actualizacion: 2026-04-21
Alcance: validacion funcional de respuestas de catalogo en Inbox antes de Fase B.

## DECISION FINAL

Usar esta plantilla como evidencia minima para cerrar Fase A.

## VALIDAR EN DOCUMENTACION OFICIAL

- WhatsApp Cloud API: https://developers.facebook.com/docs/whatsapp

## RIESGO

- Respuestas incorrectas de precio/stock por manejo incompleto de variantes.

## IMPACTO OPERATIVO

- Reduce escalaciones manuales y evita sobrepromesa comercial en chat.

## INTERVENCION HUMANA REQUERIDA

**INTERVENCION HUMANA REQUERIDA**: Si
**RESPONSABLE**: Operacion comercial + QA funcional + Tech Lead
**MOMENTO**: antes de declarar Fase A cerrada
**PASOS DUMMY O GUIADOS**:
1. Ejecutar casos UAT en tenant piloto.
2. Registrar resultado por caso (`PASS`/`FAIL`) y evidencia.
3. Clasificar fallas por severidad.
4. Repetir ejecucion tras correcciones.
**INSUMOS NECESARIOS**: tenant con catalogo real y variantes activas
**CRITERIO DE EXITO**: >=95% PASS y 0 fallas criticas abiertas

## Casos UAT (plantilla)

| ID | Intent | Mensaje de prueba | Esperado | Resultado | Evidencia |
|---|---|---|---|---|---|
| A-01 | Saludo | "Hola" | Respuesta corta, contextual, sin inventar datos | TBD | link/captura |
| A-02 | Consulta producto | "Que productos tienes?" | Lista basada en catalogo activo real | TBD | link/captura |
| A-03 | Precio producto | "Cuanto vale [producto]?" | Precio correcto desde catalogo | TBD | link/captura |
| A-04 | Stock producto | "Tienes disponible [producto]?" | Stock correcto desde catalogo | TBD | link/captura |
| A-05 | Variante color | "Tienes [producto] color negro?" | Responde por variante o escala a humano | TBD | link/captura |
| A-06 | Variante talla/modelo | "Tienes talla M de [producto]?" | Responde por variante o escala a humano | TBD | link/captura |
| A-07 | Producto inexistente | "Tienes [producto inventado]?" | No inventa; ofrece alternativa o takeover | TBD | link/captura |
| A-08 | Mensaje ambiguo | "Y en azul?" (tras hablar de un producto) | Usa contexto conversacional reciente; si no hay match exacto, pide precision sin inventar | TBD | link/captura |
| A-09 | Mensaje no-text | audio/imagen | Escala a `human_takeover` | TBD | link/captura |
| A-10 | Conversacion en takeover | "Hola" (en takeover) | Bot silenciado, sin auto-respuesta | TBD | link/captura |

## Criterio de cierre Fase A

1. Minimo 30 casos ejecutados.
2. Tasa de exito >= 95%.
3. Fallas criticas: 0 abiertas.
4. Fallas altas: mitigacion aprobada y fecha compromiso.
5. Evidencia archivada en carpeta operativa del sprint.

## Modo Free (fallback cuando Render se congela)

Si el frontend en Render Free está dormido o inestable para pruebas manuales:

1. Ejecutar validación técnica asistida desde VM:

```bash
./scripts/uat/fase_a_free_fallback.sh
```

2. Usar su salida como evidencia técnica base.
3. Completar luego la parte funcional/UAT de negocio cuando el servicio esté disponible.

Nota: este fallback no reemplaza la validación funcional de operación real con usuario, pero evita bloqueo total por cold starts.
