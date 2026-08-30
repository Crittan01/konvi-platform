'use client'

import { useState } from 'react'
import * as XLSX from 'xlsx'
import { Download, Upload, FileSpreadsheet, Loader2, CheckCircle2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { createClient } from '@/utils/supabase/client'
import { buildCategoryPicker } from '../_lib/category-tree'
import { IMPORT_COLUMNS, buildExampleRow, groupRowsToProducts, pickDataSheet } from '../_lib/import-template'

interface Props { productCategories: {id: string, display_label: string, parent_id?: string | null}[]; onImported?: () => void; tenantId: string; apiUrl: string }

export default function MassImporter({ productCategories, onImported = () => {}, apiUrl }: Props) {
  // ADR-0027/0029: la categoría OPERATIVA (la que el bot usa para agrupar) es la ÚNICA que se captura.
  // La marketplace (platform_category_id) NO se pide por producto — se deriva por categoría al publicar.
  const [selectedOpCat, setSelectedOpCat] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)

  // Columnas de la plantilla — fuente única en _lib/import-template (compartida con el parser y el test).
  const COLUMNS = IMPORT_COLUMNS

  const handleDownloadTemplate = () => {
    if (!selectedOpCat) { setError('Selecciona la categoría de catálogo primero para la plantilla.'); return }
    setError(null)
    setSuccess(null)
    const catName = productCategories.find(c => c.id === selectedOpCat)?.display_label || 'General'

    // --- Construir celdas manualmente (cabeceras + fila de ejemplo alineada) ---
    // YELLOW-4: desde la migración a SheetJS CE 0.20.3 (xlsx-js-style era un fork abandonado
    // de xlsx 0.18.5 con CVE-2023-30533 y CVE-2024-22363 HIGH) la CE NO escribe estilos de
    // celda (font/fill/border) ni paneles congelados (`!freeze`) — se eliminaron. La plantilla
    // conserva contenido, anchos de columna y alturas de fila. Si se requieren estilos otra
    // vez, NO reinstalar xlsx-js-style: evaluar exceljs (ver follow-up en osv-scanner.toml).
    const wb = XLSX.utils.book_new()
    const ws: XLSX.WorkSheet = {}

    // Fila de ejemplo ALINEADA 1:1 con COLUMNS (16 celdas) — fuente única en _lib/import-template.
    const exampleRow = buildExampleRow()

    COLUMNS.forEach((col, i) => {
      const cellRef  = XLSX.utils.encode_cell({ r: 0, c: i })
      const exRef    = XLSX.utils.encode_cell({ r: 1, c: i })
      ws[cellRef] = { v: col.label, t: 's' }
      ws[exRef]   = { v: exampleRow[i], t: typeof exampleRow[i] === 'number' ? 'n' : 's' }
    })

    // Rango de la hoja
    ws['!ref'] = XLSX.utils.encode_range({ s: { r: 0, c: 0 }, e: { r: 1, c: COLUMNS.length - 1 } })

    // Anchos de columna
    ws['!cols'] = COLUMNS.map(c => ({ wch: c.width }))

    // Altura de la fila de encabezado
    ws['!rows'] = [{ hpt: 36 }, { hpt: 20 }]

    // --- Segunda Hoja: Instrucciones ---
    const wsInstruct: XLSX.WorkSheet = {}
    const instHeaders = ['Columna', '¿Obligatorio?', 'Descripción de lo que debes llenar', 'Ejemplo']

    instHeaders.forEach((h, i) => {
      wsInstruct[XLSX.utils.encode_cell({ r: 0, c: i })] = { v: h, t: 's' }
    })

    COLUMNS.forEach((col, idx) => {
      const r = idx + 1;
      wsInstruct[XLSX.utils.encode_cell({ r, c: 0 })] = { v: col.label, t: 's' }
      wsInstruct[XLSX.utils.encode_cell({ r, c: 1 })] = { v: col.req ? '⚠️ SÍ, OBLIGATORIO' : 'Opcional', t: 's' }
      wsInstruct[XLSX.utils.encode_cell({ r, c: 2 })] = { v: col.desc, t: 's' }
      wsInstruct[XLSX.utils.encode_cell({ r, c: 3 })] = { v: exampleRow[idx], t: typeof exampleRow[idx] === 'number' ? 'n' : 's' }
    })

    wsInstruct['!ref'] = XLSX.utils.encode_range({ s: { r: 0, c: 0 }, e: { r: COLUMNS.length, c: 3 } })
    wsInstruct['!cols'] = [{ wch: 30 }, { wch: 22 }, { wch: 75 }, { wch: 30 }]
    wsInstruct['!rows'] = [{ hpt: 30 }, ...COLUMNS.map(() => ({ hpt: 45 }))]

    XLSX.utils.book_append_sheet(wb, wsInstruct, 'Instrucciones')
    XLSX.utils.book_append_sheet(wb, ws, catName.substring(0, 31))
    
    // Convertir nombre a seguro
    XLSX.writeFile(wb, `Plantilla_${catName.replace(/[^a-z0-9]/gi, '_')}.xlsx`)
  }

  const handleProcessImport = async () => {
    if (!file) { setError("Sube un archivo primero."); return }
    if (!selectedOpCat) { setError("Selecciona la categoría de catálogo bajo la que se importarán."); return }
    
    setUploading(true)
    setError(null)
    setSuccess(null)
    
    try {
      const data = await file.arrayBuffer()
      const wb = XLSX.read(data, { type: 'array' })
      // BLOQUE C item 1: elegir la hoja de DATOS por cabeceras (no SheetNames[0], que es
      // 'Instrucciones' en la plantilla oficial → antes leía las instrucciones y todo fallaba).
      const ws = pickDataSheet(wb)
      const rows = XLSX.utils.sheet_to_json<Record<string, string>>(ws, { defval: "" })

      if (rows.length === 0) throw new Error("El archivo está vacío o mal formateado.")

      // Agrupación + parseo puro (compartido con el test que verifica la plantilla).
      const { products: bulkProducts, rejected } = groupRowsToProducts(rows, selectedOpCat || null)
      // BLOQUE C item 2: filas rechazadas (precio inválido / falta Nombre-SKU) NUNCA se
      // descartan en silencio. Si TODO se rechazó, abortar con el detalle.
      if (bulkProducts.length === 0) {
        const detail = rejected.length
          ? ` Filas rechazadas: ${rejected.slice(0, 5).map(r => `fila ${r.row} (${r.reason})`).join('; ')}${rejected.length > 5 ? `; +${rejected.length - 5} más` : ''}.`
          : ''
        throw new Error(`No se importó ningún producto válido.${detail || ' Revisa la plantilla.'}`)
      }

      // F2: enruta por la API (POST /products/bulk) → hereda RBAC + @audit_log + validación de ownership;
      // antes escribía DIRECTO a Supabase desde el browser (brecha de las 4 garantías).
      const supabase = createClient()
      const { data: { session } } = await supabase.auth.getSession()
      if (!session?.access_token) throw new Error('Sesión expirada. Vuelve a iniciar sesión.')

      const bulkPayload = { products: bulkProducts }

      const res = await fetch(`${apiUrl}/api/v1/products/bulk`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${session.access_token}` },
        body: JSON.stringify(bulkPayload),
      })
      if (!res.ok) throw new Error((await res.text()) || `Error ${res.status} en la importaci\u00f3n`)
      const result = await res.json()
      const totalVars = result.variants_upserted ?? 0
      const errCount = Array.isArray(result.errors) ? result.errors.length : 0
      const rejNote = rejected.length ? ` \u00b7 ${rejected.length} fila(s) rechazada(s) (precio inv\u00e1lido o falta Nombre/SKU)` : ''

      setSuccess(`\u00a1Importaci\u00f3n! ${result.products_created ?? 0} creados, ${result.products_reused ?? 0} reusados, ${totalVars} variantes${errCount ? ` \u00b7 ${errCount} con error (revisa la plantilla)` : ''}${rejNote}.`)
      
      // Pequeño timeout antes de recargar la interfaz para que vean el éxito
      setTimeout(() => {
         setFile(null)
         onImported() // Provoca Server Action revalidatePath originario
      }, 2000)

    } catch(err) {
      setError(err instanceof Error ? err.message : "Error fatal durante la importación masiva.")
    } finally {
      setUploading(false)
    }
  }

  return (
    <Card className="border-border">
      <CardHeader className="pb-3 border-b border-border/50 bg-muted/10">
        <CardTitle className="text-base flex items-center gap-2">
          <FileSpreadsheet className="h-5 w-5 text-primary" />
          Importación Masiva (Excel)
        </CardTitle>
      </CardHeader>
      <CardContent className="pt-5 space-y-5">
        <div className="space-y-2">
          <Label>1. Define la Categoría</Label>
          {/* ADR-0029 F4: la categoría OPERATIVA (la que el bot usa) es la PRIMARIA en toda alta. */}
          <select
            value={selectedOpCat}
            onChange={e => setSelectedOpCat(e.target.value)}
            className="w-full h-10 px-3 py-2 rounded-md border border-input text-sm bg-background transition-colors focus:ring-2 focus:ring-primary focus:border-transparent"
          >
            <option value="">-- Obligatorio: Categoría de catálogo (la que ve el bot) --</option>
            {/* F2: picker agrupado — verticales como <optgroup>, subcategorías/hojas como opciones. */}
            {buildCategoryPicker(productCategories).map((g, gi) =>
              g.label === null
                ? g.options.map(o => <option key={o.id} value={o.id}>{o.display_label}</option>)
                : <optgroup key={`g-${gi}-${g.label}`} label={g.label}>
                    {g.options.map(o => <option key={o.id} value={o.id}>{o.display_label}</option>)}
                  </optgroup>
            )}
          </select>
          <p className="text-[11px] text-muted-foreground leading-snug pt-1">La categoría con la que el bot agrupa el catálogo en el chat. Todos los productos importados quedan bajo ella.</p>
        </div>

        <div className="space-y-2 pt-2 border-t border-border/40">
          <Label>2. Descarga tu Plantilla</Label>
          <Button type="button" variant="secondary" className="w-full gap-2 border shadow-xs hover:bg-primary/5! hover:text-primary transition-all" onClick={handleDownloadTemplate}>
            <Download className="h-4 w-4" /> Bajar Plantilla .xlsx
          </Button>
          
          <div className="mt-3 p-3 rounded-lg bg-warning-bg border border-warning-border text-xs text-warning-fg">
            <strong>Nota visual:</strong> La importación masiva es 100% texto para evitar complicaciones con URLs. Una vez cargues tus productos, podrás subir sus fotos directamente visualizando tu Catálogo.
          </div>
        </div>

        <div className="space-y-2 pt-4 border-t border-border/40">
          <Label>3. Sube el Excel Lleno</Label>
          <div className="flex items-center gap-2">
            <Input type="file" accept=".xlsx, .xls" onChange={e => setFile(e.target.files?.[0] || null)} className="flex-1 cursor-pointer file:cursor-pointer file:bg-primary/10 file:text-primary file:border-0 file:mr-4 file:px-4 file:py-1 file:rounded-full hover:file:bg-primary/20" />
          </div>
        </div>

        {error && <p className="text-xs text-destructive font-medium bg-destructive/10 p-2.5 rounded-lg border border-destructive/20 shadow-xs">{error}</p>}
        {success && <p className="text-xs text-success-fg font-medium bg-success-bg p-2.5 rounded-lg border border-success-border shadow-xs flex items-center gap-2"><CheckCircle2 className="h-4 w-4 shrink-0"/>{success}</p>}

        <div className="pt-2">
          <Button type="button" className="w-full gap-2 font-medium" onClick={handleProcessImport} disabled={uploading}>
            {uploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
            {uploading ? 'Importando productos...' : 'Importar productos'}
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
