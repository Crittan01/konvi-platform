/**
 * Visor de documentos legales (F6).
 *
 * Renderiza el Markdown de docs/legal/*.md como HTML legible y con el layout de
 * la consola, en vez de servir el .md crudo desde /public. El slug se valida
 * contra una whitelist (LEGAL_DOCS) → no hay path traversal.
 */
import { readFile } from 'node:fs/promises'
import path from 'node:path'
import Link from 'next/link'
import { notFound } from 'next/navigation'
import { ArrowLeft, Scale } from 'lucide-react'
import { PageHeader } from '@/components/ui/page-header'
import { renderMarkdown, LEGAL_DOCS } from '../../_lib/markdown'

// force-DYNAMIC, no static: la página vive bajo el layout autenticado del
// dashboard (lee cookies de sesión en cada request). Con `force-static` el
// layout no recibía las cookies → getUser()=null → redirect a /login: el
// visor quedaba INALCANZABLE (bug pre-existente expuesto por la sonda T7.12).
export const dynamic = 'force-dynamic'

export default async function LegalDocViewer({
  params,
}: {
  params: Promise<{ doc: string }>
}) {
  const { doc } = await params
  const entry = LEGAL_DOCS[doc]
  if (!entry) notFound()

  let markdown: string
  try {
    const filePath = path.join(process.cwd(), 'public', 'docs', 'legal', entry.file)
    markdown = await readFile(filePath, 'utf8')
  } catch {
    notFound()
  }

  const html = renderMarkdown(markdown!)

  return (
    <div className="max-w-3xl mx-auto p-6 space-y-5">
      <Link
        href="/dashboard/settings/legal"
        className="inline-flex items-center gap-1.5 text-sm text-primary hover:underline"
      >
        <ArrowLeft className="h-4 w-4" aria-hidden="true" /> Volver a Aceptación legal
      </Link>

      {/* Cabecera de módulo con identidad (firma Kaiu, T7.12) */}
      <PageHeader icon={Scale} title={entry.title} />

      <article
        className="md-doc text-sm text-foreground/90 leading-relaxed"
        dangerouslySetInnerHTML={{ __html: html }}
      />

      <style>{`
        .md-doc > * + * { margin-top: 0.85rem; }
        .md-doc .md-h1 { font-size: 1.4rem; font-weight: 700; margin-top: 1.5rem; }
        .md-doc .md-h2 { font-size: 1.15rem; font-weight: 700; margin-top: 1.4rem; }
        .md-doc .md-h3 { font-size: 1rem; font-weight: 600; margin-top: 1.1rem; }
        .md-doc .md-h4, .md-doc .md-h5, .md-doc .md-h6 { font-size: 0.9rem; font-weight: 600; margin-top: 1rem; }
        .md-doc .md-ul, .md-doc .md-ol { padding-left: 1.4rem; }
        .md-doc .md-ul { list-style: disc; }
        .md-doc .md-ol { list-style: decimal; }
        .md-doc .md-ul li, .md-doc .md-ol li { margin-top: 0.3rem; }
        .md-doc .md-quote {
          border-left: 3px solid rgba(120,120,120,0.4);
          padding: 0.5rem 0.9rem; opacity: 0.85; font-style: italic;
        }
        .md-doc .md-hr { border: 0; border-top: 1px solid rgba(120,120,120,0.25); margin: 1.2rem 0; }
        .md-doc .md-code {
          font-family: ui-monospace, monospace; font-size: 0.85em;
          background: rgba(120,120,120,0.12); padding: 0.1em 0.35em; border-radius: 0.25rem;
        }
        .md-doc .md-link { color: #1d4ed8; text-decoration: underline; }
        .md-doc .md-table-wrap { overflow-x: auto; }
        .md-doc .md-table { width: 100%; border-collapse: collapse; font-size: 0.82rem; }
        .md-doc .md-table th, .md-doc .md-table td {
          border: 1px solid rgba(120,120,120,0.25); padding: 0.4rem 0.6rem; text-align: left; vertical-align: top;
        }
        .md-doc .md-table th { font-weight: 600; background: rgba(120,120,120,0.08); }
      `}</style>
    </div>
  )
}
