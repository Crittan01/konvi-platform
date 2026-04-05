# Local Development Environment

## Definición
El entorno local de este proyecto es una VM dedicada al proyecto, accesible por Remote SSH.

## Decisión actual
- Host: Fedora 43
- Virtualización: KVM
- Guest recomendado: Fedora Server o equivalente Linux orientado a desarrollo
- Workspace del proyecto: repo aislado dentro de la VM

## Objetivos del local
- aislamiento del proyecto
- reglas del agente específicas sin contaminar otros proyectos
- secretos separados
- tooling consistente
- desarrollo backend/frontend/documentación
- pruebas locales controladas

## Reglas
- desarrollar dentro del filesystem Linux de la VM
- no mezclar tooling del proyecto con otros repos
- no exponer secrets en el repo
- mantener el workspace autocontenido

## Herramientas mínimas esperadas
- git
- python
- node
- package manager del monorepo
- editor con Remote SSH
- Antigravity apuntando al workspace del repo

## Consideraciones
- webhooks externos pueden requerir túneles o staging más adelante
- el entorno local no reemplaza producción
- staging se añadirá cuando entren integraciones reales sensibles

## Estado de ambientes
- local: VM dedicada
- prod: Render + Supabase
- staging: diferido hasta necesidad real
