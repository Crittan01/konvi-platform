# Secrets and Config

## Objetivo
Definir cómo se manejan variables de entorno, secretos y configuración por ambiente.

## Principios
- no exponer secretos en frontend
- no guardar secretos en el repo
- separar configuración por ambiente
- usar nombres consistentes para variables

## Ambientes previstos
- local
- production
- staging futuro

## Categorías de configuración
- app
- API
- Supabase
- WhatsApp
- Telegram
- Mercado Libre
- Shopify futuro
- observabilidad

## Regla
Toda variable sensible debe documentarse con:
- nombre
- propósito
- ambiente
- responsable de provisión
- si requiere intervención humana