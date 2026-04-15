# Operations Manual: Commerce Ops Platform (AI Agent Mode)

This file is the primary entry point for AI Agents (Claude Code, Antigravity, etc.). Follow these guidelines to interact with this repository efficiently.

## Project Context
- **Purpose**: Multi-tenant SaaS for conversational e-commerce via WhatsApp.
- **Reality Hub**: Refer to [AGENTS.md](AGENTS.md) for the "certified truth" list.

## Core Commands (Render Free Compliance)
| Action | Command |
|---|---|
| Verify Code | `pnpm --filter web lint` / `pnpm --filter web type-check` |
| DB Audit | `supabase db query --linked "SQL_QUERY"` |
| Start Dev | `pnpm --filter web dev` |
| Health Check | `curl https://commerce-ops-api.onrender.com/health` |

## Identity Verification
- **Framework**: Next.js 14.2.35 (App Router).
- **Backend**: FastAPI (Python 3.11.13) + Supabase RLS.
- **Isolation Strategy**: `tenant_id` mandatory in all queries/API calls.

## Documentation Hierarchy
1. **Entry Point**: `AGENTS.md`
2. **Current State**: `.context/01-state.md`
3. **Architecture Snapshots**: `docs/tech/*.md` (Verified Reality).

---

## Instructions for the Agent
- **Never Assume**: If something isn't in `docs/tech/`, it doesn't exist or isn't certified.
- **Empirical first**: Use `supabase db query` or `grep` to verify implementation details before documenting or building on top.
- **No Placeholders**: Never use placeholder IDs or credentials. Use context-resolved `tenant_id`.
