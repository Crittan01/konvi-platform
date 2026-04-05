# API Service

## Objetivo
Servicio backend principal de la plataforma.

## Responsabilidades previstas
- exponer APIs del producto
- validar auth y permisos
- aplicar reglas multi-tenant
- coordinar módulos de negocio
- publicar trabajo asincrónico cuando corresponda

## No debe hacer
- procesamiento pesado en request path
- lógica de sync larga
- depender del LLM como fuente de verdad