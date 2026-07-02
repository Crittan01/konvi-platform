'use client'

import { useState } from 'react'
import * as XLSX from 'xlsx-js-style'
import { Download, Upload, FileSpreadsheet, Loader2, CheckCircle2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { createClient } from '@/utils/supabase/client'
import { buildCategoryPicker } from '../_lib/category-tree'

interface Props { productCategories: {id: string, display_label: string, parent_id?: string | null}[]; onImported?: () => void; tenantId: string; apiUrl: string }

// Forma de una variante derivada de una fila del Excel (post-parseo de celdas)
type ImportVariant = {
  sku: string
  attrKey: string
  attrVal: string
  attrKey2: string
  attrVal2: string
  attrKey3: string
  attrVal3: string
  pNormal: number
  pPromo: number | null
  stock: number
  weight: number | null
  length: number | null
  width: number | null
  height: number | null
  vImg: string | null
}

export default function MassImporter({ productCategories, onImported = () => {}, apiUrl }: Props) {
  // ADR-0027/0029: la categoría OPERATIVA (la que el bot usa para agrupar) es la ÚNICA que se captura.
  // La marketplace (platform_category_id) NO se pide por producto — se deriva por categoría al publicar.
  const [selectedOpCat, setSelectedOpCat] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)

  // Columnas amigables, ancho, obligatoriedad y descripción
  const COLUMNS: { label: string; key: string; width: number; req: boolean; desc: string }[] = [
    { label: 'SKU (Obligatorio)',           key: 'sku',        width: 24, req: true,  desc: 'Identificador único del producto o variante (Ej: JAB-001-20M)' },
    { label: 'Nombre del Producto',         key: 'nombre',     width: 30, req: true,  desc: 'Nombre principal. Si varias filas tienen el mismo nombre, se agrupan en un solo producto con varias opciones.' },
    { label: 'Descripción',                key: 'desc',       width: 40, req: false, desc: 'Detalle largo del producto (Solo se procesará el de la primera fila del grupo)' },
    { label: 'Atributo 1 (Ej: Color)',       key: 'attrKey',   width: 24, req: false, desc: 'Primera propiedad que distingue esta variante. Ej: Color, Talla, Tamaño.' },
    { label: 'Valor 1 (Ej: Rojo)',           key: 'attrVal',   width: 22, req: false, desc: 'Valor del atributo 1. Ej: Rojo, M, 50ml.' },
    { label: 'Atributo 2 (Ej: Talla)',       key: 'attrKey2',  width: 24, req: false, desc: 'Segunda propiedad (opcional). Ej: si ya usaste Color, aquí Talla.' },
    { label: 'Valor 2 (Ej: M)',              key: 'attrVal2',  width: 22, req: false, desc: 'Valor del atributo 2. Ej: M, XL, 100ml.' },
    { label: 'Atributo 3 (Ej: Aroma)',       key: 'attrKey3',  width: 24, req: false, desc: 'Tercera propiedad (opcional). Para productos con 3 variantes.' },
    { label: 'Valor 3 (Ej: Lavanda)',        key: 'attrVal3',  width: 22, req: false, desc: 'Valor del atributo 3. Ej: Lavanda, Natural, Extra.' },
    { label: 'Precio Normal ($)',           key: 'precioNormal', width: 22, req: true,  desc: 'Precio base de venta al público. Solo números y sin comas.' },
    { label: 'Precio Promocional ($)',      key: 'precioPromo',  width: 26, req: false, desc: 'Opcional. Si lo llenas, este será el precio final y el Normal aparecerá tachado.' },
    { label: 'Cantidad en Stock',           key: 'stock',      width: 20, req: true,  desc: 'Unidades exactas disponibles en tu bodega.' },
    { label: 'Peso en kilos (kg)',          key: 'peso',       width: 20, req: false, desc: 'Valor numérico para calcular costos de envío (Ej: 1.5).' },
    { label: 'Largo del empaque (cm)',      key: 'largo',      width: 24, req: false, desc: 'Medida del paquete enviado.' },
    { label: 'Ancho del empaque (cm)',      key: 'ancho',      width: 24, req: false, desc: 'Medida del paquete enviado.' },
    { label: 'Alto del empaque (cm)',       key: 'alto',       width: 24, req: false, desc: 'Medida del paquete enviado.' }
  ]

  const handleDownloadTemplate = () => {
    if (!selectedOpCat) { setError('Selecciona la categoría de catálogo primero para la plantilla.'); return }
    setError(null)
    setSuccess(null)
    const catName = productCategories.find(c => c.id === selectedOpCat)?.display_label || 'General'

    // --- Construir celdas manualmente para poder aplicar estilos ---
    const wb = XLSX.utils.book_new()
    const ws: XLSX.WorkSheet = {}

    // Estilo de cabecera obligatoria (Rojo)
    const reqHeaderStyle = {
      font: { bold: true, color: { rgb: 'FFFFFF' }, sz: 12, name: 'Arial' },
      fill: { fgColor: { rgb: 'B91C1C' }, patternType: 'solid' as const }, 
      alignment: { horizontal: 'center' as const, vertical: 'center' as const, wrapText: true },
      border: {
        bottom: { style: 'medium', color: { rgb: '7F1D1D' } },
        right:  { style: 'thin',   color: { rgb: '7F1D1D' } },
      }
    }

    // Estilo de cabecera opcional (Indigo)
    const optHeaderStyle = {
      font: { bold: true, color: { rgb: 'FFFFFF' }, sz: 11, name: 'Arial' },
      fill: { fgColor: { rgb: '4338CA' }, patternType: 'solid' as const },
      alignment: { horizontal: 'center' as const, vertical: 'center' as const, wrapText: true },
      border: {
        bottom: { style: 'medium', color: { rgb: '312E81' } },
        right:  { style: 'thin',   color: { rgb: '312E81' } },
      }
    }

    // Estilo de fila de ejemplo
    const exampleStyle = {
      font: { color: { rgb: '6B7280' }, sz: 10, italic: true },
      fill: { fgColor: { rgb: 'F3F4F6' }, patternType: 'solid' as const },
      alignment: { horizontal: 'left' as const }
    }

    const exampleRow = [
      'VAR-ZAP-001-ROJO', 'Zapatillas Comfort Pro', 'Zapatilla deportiva premium para hombre y mujer',
      'Color', 'Rojo', 120000, 85000, 10, 0.65, 32, 18, 12
    ]

    COLUMNS.forEach((col, i) => {
      const cellRef  = XLSX.utils.encode_cell({ r: 0, c: i })
      const exRef    = XLSX.utils.encode_cell({ r: 1, c: i })
      ws[cellRef] = { v: col.label, t: 's', s: col.req ? reqHeaderStyle : optHeaderStyle }
      ws[exRef]   = { v: exampleRow[i], t: typeof exampleRow[i] === 'number' ? 'n' : 's', s: exampleStyle }
    })

    // Rango de la hoja
    ws['!ref'] = XLSX.utils.encode_range({ s: { r: 0, c: 0 }, e: { r: 1, c: COLUMNS.length - 1 } })

    // Anchos de columna
    ws['!cols'] = COLUMNS.map(c => ({ wch: c.width }))

    // Altura de la fila de encabezado
    ws['!rows'] = [{ hpt: 36 }, { hpt: 20 }]

    // Congelar primera fila principal
    ws['!freeze'] = { xSplit: 0, ySplit: 1 }

    // --- Segunda Hoja: Instrucciones ---
    const wsInstruct: XLSX.WorkSheet = {}
    const instHeaders = ['Columna', '¿Obligatorio?', 'Descripción de lo que debes llenar', 'Ejemplo']
    
    instHeaders.forEach((h, i) => {
      wsInstruct[XLSX.utils.encode_cell({ r: 0, c: i })] = { v: h, t: 's', s: optHeaderStyle }
    })

    COLUMNS.forEach((col, idx) => {
      const r = idx + 1;
      const baseFont = { font: { name: 'Arial', sz: 10 } }
      wsInstruct[XLSX.utils.encode_cell({ r, c: 0 })] = { v: col.label, t: 's', s: { font: { bold: true, name: 'Arial', sz: 10 } } }
      
      wsInstruct[XLSX.utils.encode_cell({ r, c: 1 })] = { 
        v: col.req ? '⚠️ SÍ, OBLIGATORIO' : 'Opcional', 
        t: 's', 
        s: { font: { color: { rgb: col.req ? 'B91C1C' : '6B7280' }, bold: col.req, name: 'Arial', sz: 10 }, alignment: { horizontal: 'center' } } 
      }
      
      wsInstruct[XLSX.utils.encode_cell({ r, c: 2 })] = { v: col.desc, t: 's', s: { ...baseFont, alignment: { wrapText: true, vertical: 'center' } } }
      wsInstruct[XLSX.utils.encode_cell({ r, c: 3 })] = { v: exampleRow[idx], t: typeof exampleRow[idx] === 'number' ? 'n' : 's', s: { font: { italic: true, color: { rgb: '4B5563' }, name: 'Arial' } } }
    })

    wsInstruct['!ref'] = XLSX.utils.encode_range({ s: { r: 0, c: 0 }, e: { r: COLUMNS.length, c: 3 } })
    wsInstruct['!cols'] = [{ wch: 30 }, { wch: 22 }, { wch: 75 }, { wch: 30 }]
    wsInstruct['!rows'] = [{ hpt: 30 }, ...COLUMNS.map(() => ({ hpt: 45 }))]
    wsInstruct['!freeze'] = { xSplit: 0, ySplit: 1 }

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
      const ws = wb.Sheets[wb.SheetNames[0]]
      const rows = XLSX.utils.sheet_to_json<Record<string, string>>(ws, { defval: "" })

      if (rows.length === 0) throw new Error("El archivo está vacío o mal formateado.")

      // Agrupamos filas por Nombre del Producto para saber qué son Variantes del mismo
      const productsMap: Record<string, { desc: string, img: string | null, variants: ImportVariant[] }> = {}
      for (const row of rows) {
        const pName = row['Nombre del Producto']?.toString().trim()
        const sku = row['SKU (Obligatorio)']?.toString().trim()
        if (!pName || !sku) continue

        if (!productsMap[pName]) {
          productsMap[pName] = {
            desc: row['Descripción']?.toString().trim(),
            img: null,
            variants: []
          }
        }
        
        productsMap[pName].variants.push({
          sku: sku,
          attrKey: row['Atributo 1 (Ej: Color)']?.toString().trim() || 'Genérico',
          attrVal: row['Valor 1 (Ej: Rojo)']?.toString().trim()    || 'Estándar',
          attrKey2: row['Atributo 2 (Ej: Talla)']?.toString().trim() || '',
          attrVal2: row['Valor 2 (Ej: M)']?.toString().trim()        || '',
          attrKey3: row['Atributo 3 (Ej: Aroma)']?.toString().trim() || '',
          attrVal3: row['Valor 3 (Ej: Lavanda)']?.toString().trim()   || '',
          pNormal: parseFloat(row['Precio Normal ($)']) || 0,
          pPromo: parseFloat(row['Precio Promocional ($)']) || null,
          stock: parseInt(row['Cantidad en Stock']) || 0,
          weight: parseFloat(row['Peso en kilos (kg)']) || null,
          length: parseFloat(row['Largo del empaque (cm)']) || null,
          width: parseFloat(row['Ancho del empaque (cm)']) || null,
          height: parseFloat(row['Alto del empaque (cm)']) || null,
          vImg: null
        })
      }

      const pNames = Object.keys(productsMap)
      if (pNames.length === 0) throw new Error("No se encontraron productos válidos para importar (falta Nombre o SKU). Revisa la plantilla.")

      // F2: enruta por la API (POST /products/bulk) → hereda RBAC + @audit_log + validación de ownership;
      // antes escribía DIRECTO a Supabase desde el browser (brecha de las 4 garantías).
      const supabase = createClient()
      const { data: { session } } = await supabase.auth.getSession()
      if (!session?.access_token) throw new Error('Sesión expirada. Vuelve a iniciar sesión.')

      const bulkPayload = {
        products: pNames.map(pName => {
          const prodData = productsMap[pName]
          return {
            title: pName,
            description: prodData.desc || null,
            cover_image_url: prodData.img || null,
            category_id: selectedOpCat || null,
            variations: prodData.variants.map((v) => {
              let price = v.pNormal > 0 ? v.pNormal : 1
              let compare_at_price = null
              if (v.pPromo && v.pPromo > 0) { price = v.pPromo; compare_at_price = v.pNormal }
              return {
                sku: v.sku,
                price,
                compare_at_price,
                cost_price: 0,
                stock_quantity: v.stock,
                attributes: Object.fromEntries([
                  [v.attrKey, v.attrVal],
                  ...(v.attrKey2 && v.attrVal2 ? [[v.attrKey2, v.attrVal2]] : []),
                  ...(v.attrKey3 && v.attrVal3 ? [[v.attrKey3, v.attrVal3]] : []),
                ].filter(([k]) => k && k !== 'Gen\u00e9rico')),
                weight_kg: v.weight,
                length_cm: v.length,
                width_cm: v.width,
                height_cm: v.height,
                image_url: v.vImg,
              }
            }),
          }
        }),
      }

      const res = await fetch(`${apiUrl}/api/v1/products/bulk`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${session.access_token}` },
        body: JSON.stringify(bulkPayload),
      })
      if (!res.ok) throw new Error((await res.text()) || `Error ${res.status} en la importaci\u00f3n`)
      const result = await res.json()
      const totalVars = result.variants_upserted ?? 0
      const errCount = Array.isArray(result.errors) ? result.errors.length : 0

      setSuccess(`\u00a1Importaci\u00f3n! ${result.products_created ?? 0} creados, ${result.products_reused ?? 0} reusados, ${totalVars} variantes${errCount ? ` \u00b7 ${errCount} con error (revisa la plantilla)` : ''}.`)
      
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
          <Button type="button" variant="secondary" className="w-full gap-2 border shadow-sm hover:!bg-primary/5 hover:text-primary transition-all" onClick={handleDownloadTemplate}>
            <Download className="h-4 w-4" /> Bajar Plantilla .xlsx
          </Button>
          
          <div className="mt-3 p-3 rounded-lg bg-amber-500/10 border border-amber-500/20 text-xs text-amber-700 dark:text-amber-400">
            <strong>Nota visual:</strong> La importación masiva es 100% texto para evitar complicaciones con URLs. Una vez cargues tus productos, podrás subir sus fotos directamente visualizando tu Catálogo.
          </div>
        </div>

        <div className="space-y-2 pt-4 border-t border-border/40">
          <Label>3. Sube el Excel Lleno</Label>
          <div className="flex items-center gap-2">
            <Input type="file" accept=".xlsx, .xls" onChange={e => setFile(e.target.files?.[0] || null)} className="flex-1 cursor-pointer file:cursor-pointer file:bg-primary/10 file:text-primary file:border-0 file:mr-4 file:px-4 file:py-1 file:rounded-full hover:file:bg-primary/20" />
          </div>
        </div>

        {error && <p className="text-xs text-destructive font-medium bg-destructive/10 p-2.5 rounded-lg border border-destructive/20 shadow-sm">{error}</p>}
        {success && <p className="text-xs text-green-600 dark:text-green-400 font-medium bg-green-500/10 p-2.5 rounded-lg border border-green-500/20 shadow-sm flex items-center gap-2"><CheckCircle2 className="h-4 w-4 shrink-0"/>{success}</p>}

        <div className="pt-2">
          <Button type="button" className="w-full gap-2 font-medium" onClick={handleProcessImport} disabled={uploading}>
            {uploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
            {uploading ? 'Procesando inyección...' : 'Iniciar Inyección Automática'}
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
