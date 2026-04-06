import os

base_dir = "/home/ansible/workspaces/commerce-ops-platform"

directories = [
    ".agents/rules",
    ".agents/workflows",
    ".agents/skills",
    "docs/product",
    "docs/architecture",
    "docs/ai",
    "docs/data",
    "docs/integrations",
    "docs/deployment",
    "docs/operations",
    "docs/research",
    "docs/roadmap",
    "docs/risks",
    "apps/web",
    "services/api",
    "services/worker",
    "services/cron",
    "services/ai-orchestrator",
    "services/connector-whatsapp",
    "services/connector-mercadolibre",
    "services/connector-shopify",
    "packages/shared-types",
    "packages/ui",
    "packages/config",
    "packages/db",
    "packages/auth",
    "packages/observability",
    "packages/test-utils",
    "infra/render",
    "infra/supabase",
    "infra/local",
    "scripts",
    "tests"
]

for d in directories:
    os.makedirs(os.path.join(base_dir, d), exist_ok=True)

print("Directories created.")
