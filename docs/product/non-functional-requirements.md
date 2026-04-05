# Non-Functional Requirements

## Objetivo
Definir las cualidades del sistema necesarias para operación real.

## 1. Seguridad
- El sistema debe garantizar aislamiento multi-tenant real.
- Toda entidad sensible debe considerar tenant_id.
- Toda tabla sensible debe protegerse con RLS.
- El frontend no debe ser la única capa de autorización.
- El service role nunca debe exponerse al cliente.
- Toda acción sensible debe poder auditarse.

## 2. Auditabilidad
- El sistema debe registrar cambios relevantes de catálogo, stock, pedidos, integraciones, permisos y administración de plataforma.
- El sistema debe registrar accesos administrativos especiales.
- El sistema debe registrar errores de sincronización y procesos automáticos.

## 3. Mantenibilidad
- La arquitectura debe ser modular.
- Los conectores externos deben estar desacoplados del core.
- Las decisiones sensibles deben documentarse con base en documentación oficial.
- El sistema debe poder crecer a nuevos canales sin reescribir el núcleo.

## 4. Escalabilidad razonable
- El sistema debe soportar múltiples tenants sin mezclar datos.
- Los procesos pesados deben correr fuera del request principal.
- El sistema debe separar procesamiento asincrónico de interacción en línea.

## 5. Observabilidad
- Debe existir logging técnico y funcional.
- Deben existir métricas por tenant e integración.
- Deben existir alertas operativas mínimas.
- Debe existir trazabilidad de costos de IA y fallos de conectores.

## 6. Usabilidad operativa
- El panel debe ser útil para operación diaria.
- El usuario debe poder administrar catálogo, stock, conversaciones e integraciones sin depender de intervención técnica constante.
- La información más importante debe estar visible en paneles operativos y vistas de detalle.

## 7. Portabilidad y despliegue
- El entorno local debe ser reproducible.
- Debe existir separación entre local y producción.
- El despliegue debe poder repetirse con bajo riesgo.
- La configuración sensible debe vivir fuera del código.

## 8. Resiliencia operativa
- Los jobs asincrónicos deben manejar reintentos.
- Deben existir mecanismos de reconciliación para integraciones externas.
- Un fallo de una integración no debe comprometer el núcleo completo del sistema.

## 9. Cumplimiento de canal
- El sistema debe usar integraciones oficiales para WhatsApp.
- Debe respetar políticas, flujos y limitaciones del proveedor.
- Toda funcionalidad dependiente de proveedor debe validarse contra documentación oficial vigente antes de implementarse.