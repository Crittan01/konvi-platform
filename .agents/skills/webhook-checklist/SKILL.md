---
name: webhook-checklist
description: Use this skill when designing, reviewing or implementing webhook-based integrations to ensure verification, idempotency, retries, security and operational handling are not missed.
---

# Webhook Checklist Skill

## Purpose
Standardize webhook design and review for production integrations.

## Apply to
- WhatsApp webhooks
- Mercado Libre notifications
- Shopify webhooks in future
- any inbound event endpoint from third parties

## Checklist
1. Verify official provider documentation for webhook model.
2. Define signature validation or equivalent verification if supported.
3. Ensure the handler responds quickly.
4. Persist the minimum event envelope if needed.
5. Move heavy work to async processing.
6. Design idempotency.
7. Design retry handling.
8. Design duplicate-event tolerance.
9. Log tenant context where applicable.
10. Record operational failures and reconciliation strategy.

## Output format
Always summarize:
- verification method
- retry model
- idempotency strategy
- async handoff
- audit/logging needs
- security risks
- human setup needed