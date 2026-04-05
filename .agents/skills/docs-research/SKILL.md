---
name: docs-research
description: Use this skill when a task depends on vendor documentation, API capabilities, auth flows, policies, limits, scopes, pricing or operational constraints that must be verified before deciding or implementing.
---

# Docs Research Skill

## Purpose
Force disciplined vendor-documentation-first reasoning before architecture or implementation.

## When to use
Use this skill when the task depends on:
- official APIs
- policies
- limits
- pricing
- auth/scopes
- webhooks
- deployment platform behavior
- cloud/storage/realtime/queue capabilities

## Procedure
1. Identify the exact provider and feature involved.
2. Identify the official documentation that must be reviewed.
3. Summarize:
   - confirmed capabilities
   - confirmed constraints
   - unresolved points
   - human steps required
4. Do not invent implementation details not confirmed by the docs.
5. Before proposing architecture or code, state:
   - DECISION FINAL
   - VALIDAR EN DOCUMENTACION OFICIAL
   - RIESGO
   - INTERVENCION HUMANA REQUERIDA

## Providers of interest in this project
- Supabase
- Render
- Meta / WhatsApp
- Telegram
- Mercado Libre
- Shopify
- Gemini API / Antigravity