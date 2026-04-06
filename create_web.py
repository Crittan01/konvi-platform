import os

base_dir = "/home/ansible/workspaces/commerce-ops-platform/apps/web"
app_dir = os.path.join(base_dir, "app")
login_dir = os.path.join(app_dir, "login")

os.makedirs(login_dir, exist_ok=True)

files = {
    "package.json": """{
  "name": "web",
  "version": "0.1.0",
  "private": true,
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "start": "next start",
    "lint": "next lint"
  },
  "dependencies": {
    "@commerce/auth": "workspace:*",
    "@commerce/db": "workspace:*",
    "next": "14.1.0",
    "react": "^18",
    "react-dom": "^18",
    "lucide-react": "^0.323.0",
    "tailwindcss": "^3.3.0"
  },
  "devDependencies": {
    "typescript": "^5",
    "@types/node": "^20",
    "@types/react": "^18",
    "@types/react-dom": "^18"
  }
}
""",
    "tsconfig.json": """{
  "compilerOptions": {
    "lib": ["dom", "dom.iterable", "esnext"],
    "allowJs": true,
    "skipLibCheck": true,
    "strict": true,
    "noEmit": true,
    "esModuleInterop": true,
    "module": "esnext",
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "jsx": "preserve",
    "incremental": true,
    "plugins": [
      {
        "name": "next"
      }
    ],
    "paths": {
      "@/*": ["./*"]
    }
  },
  "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx", ".next/types/**/*.ts"],
  "exclude": ["node_modules"]
}
""",
    "tailwind.config.ts": """import type { Config } from 'tailwindcss'

const config: Config = {
  content: [
    './app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {},
  },
  plugins: [],
}
export default config
""",
    "middleware.ts": """import { type NextRequest } from 'next/server'
// import { updateSession } from '@commerce/auth/middleware' // Módulo privado referenciado teóricamente

export async function middleware(request: NextRequest) {
  // SSR Proxy: 
  // Intercepta peticiones protegidas (Dashboard, Panel) y refresca el Token validando custom claims.
  
  // return await updateSession(request)
  return;
}

export const config = {
  matcher: [
    '/((?!_next/static|_next/image|favicon.ico|.*\\\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)',
  ],
}
""",
    "app/layout.tsx": """import './globals.css'
import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'Commerce Ops Platform',
  description: 'Multi-Tenant Backoffice for WhatsApp Commerce',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  )
}
""",
    "app/globals.css": """@tailwind base;
@tailwind components;
@tailwind utilities;
""",
    "app/page.tsx": """// Lógica principal
export default function Home() {
  return (
    <main className="flex min-h-screen flex-col items-center p-24">
      <h1>Commerce Ops Platform Dashboard</h1>
    </main>
  );
}
""",
    "app/login/page.tsx": """export default function LoginPage() {
  return (
    <div className="flex justify-center items-center h-screen">
      <form>
        <h2>Sign In (Backoffice Tenant)</h2>
      </form>
    </div>
  )
}
"""
}

for filepath, content in files.items():
    full_path = os.path.join(base_dir, filepath)
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(content.strip() + "\\n")
    print("Created:", full_path)
