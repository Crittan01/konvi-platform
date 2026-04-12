'use client'

import { useState } from 'react'
import * as XLSX from 'xlsx-js-style'
import { Download, Upload, FileSpreadsheet, Loader2, CheckCircle2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { createClient } from '@/utils/supabase/client'

interface Props { categories: {id: string, name: string}[]; onImported?: () => void; tenantId: string }

export default function MassImporter({ categories, onImported = () => {}, tenantId }: Props) {
  const [selectedCat, setSelectedCat] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)

  // Columnas amigables y su ancho en caracteres
  const COLUMNS: { label: string; key: string; width: number }[] = [
    { label: 'SKU (Obligatorio)',           key: 'sku',        width: 22 },
    { label: 'Nombre del Producto',         key: 'nombre',     width: 30 },
    { label: 'Descripción',                key: 'desc',       width: 40 },
    { label: 'Tipo de Variante (Ej: Talla)', key: 'attrKey',  width: 25 },
    { label: 'Valor Variante (Ej: L)',      key: 'attrVal',    width: 22 },
    { label: 'Precio Normal ($)',           key: 'precioNormal', width: 22 },
    { label: 'Precio Promocional ($)',      key: 'precioPromo',  width: 26 },
    { label: 'Cantidad en Stock',           key: 'stock',      width: 20 },
    { label: 'Peso en kilos (kg)',          key: 'peso',       width: 20 },
    { label: 'Largo del empaque (cm)',      key: 'largo',      width: 22 },
    { label: 'Ancho del empaque (cm)',      key: 'ancho',      width: 22 },
    { label: 'Alto del empaque (cm)',       key: 'alto',       width: 22 }
  ]

  const handleDownloadTemplate = () => {
    if (!selectedCat) { setError('Selecciona una categoría primero para la plantilla.'); return }
    setError(null)
    setSuccess(null)
    const catName = categories.find(c => c.id === selectedCat)?.name || 'General'

    // --- Construir celdas manualmente para poder aplicar estilos ---
    const wb = XLSX.utils.book_new()
    const ws: XLSX.WorkSheet = {}

    // Estilo de cabecera
    const headerStyle = {
      font: { bold: true, color: { rgb: 'FFFFFF' }, sz: 11, name: 'Arial' },
      fill: { fgColor: { rgb: '4338CA' }, patternType: 'solid' as const },
      alignment: { horizontal: 'center' as const, vertical: 'center' as const, wrapText: true },
      border: {
        bottom: { style: 'medium', color: { rgb: '6D28D9' } },
        right:  { style: 'thin',   color: { rgb: '6D28D9' } },
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
      ws[cellRef] = { v: col.label, t: 's', s: headerStyle }
      ws[exRef]   = { v: exampleRow[i], t: typeof exampleRow[i] === 'number' ? 'n' : 's', s: exampleStyle }
    })

    // Rango de la hoja
    ws['!ref'] = XLSX.utils.encode_range({ s: { r: 0, c: 0 }, e: { r: 1, c: COLUMNS.length - 1 } })

    // Anchos de columna
    ws['!cols'] = COLUMNS.map(c => ({ wch: c.width }))

    // Altura de la fila de encabezado
    ws['!rows'] = [{ hpt: 36 }, { hpt: 20 }]

    // Congelar primera fila
    ws['!freeze'] = { xSplit: 0, ySplit: 1 }

    XLSX.utils.book_append_sheet(wb, ws, catName.substring(0, 31))
    XLSX.writeFile(wb, `Plantilla_${catName.replace(/[^a-z0-9]/gi, '_')}.xlsx`)
  }

  const handleProcessImport = async () => {
    if (!file) { setError("Sube un archivo primero."); return }
    if (!selectedCat) { setError("Selecciona bajo qué categoría se importarán."); return }
    
    setUploading(true)
    setError(null)
    setSuccess(null)
    
    try {
      const data = await file.arrayBuffer()
      const wb = XLSX.read(data, { type: 'array' })
      const ws = wb.Sheets[wb.SheetNames[0]]
      const rows = XLSX.utils.sheet_to_json<any>(ws, { defval: "" })

      if (rows.length === 0) throw new Error("El archivo está vacío o mal formateado.")

      // Agrupamos filas por Nombre del Producto para saber qué son Variantes del mismo
      const productsMap: Record<string, { desc: string, img: string | null, variants: any[] }> = {}
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
          attrKey: row['Tipo de Variante (Ej: Talla)']?.toString().trim() || 'Genérico',
          attrVal: row['Valor Variante (Ej: L)']?.toString().trim() || 'Estándar',
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

      const supabase = createClient()
      let totalVars = 0
      
      // Procesamos secuencialmente producto por producto
      for (const pName of pNames) {
        const prodData = productsMap[pName]
        let productId: string

        // 1. Check if base product already exists by title
        const { data: existingProd, error: findErr } = await supabase
          .from('products')
          .select('id')
          .eq('tenant_id', tenantId)
          .eq('title', pName)
          .limit(1)
          .single()

        if (existingProd) {
          productId = existingProd.id
          // Optional: Update existing product details? Let's leave them or update status to active
          await supabase.from('products').update({ status: 'active' }).eq('id', productId)
        } else {
          // Inyectamos Nuevo Producto Base
          const { data: prodResp, error: prodErr } = await supabase.from('products').insert({
            tenant_id: tenantId,
            title: pName,
            description: prodData.desc || null,
            cover_image_url: prodData.img || null,
            platform_category_id: selectedCat,
            status: 'active'
          }).select().single()

          if (prodErr || !prodResp) throw new Error(prodErr?.message || "Error insertando producto " + pName)
          productId = prodResp.id
        }

        // 2. Inyectamos / Upsertamos Variantes
        const varsToUpsert = prodData.variants.map((v: any) => {
          let price = v.pNormal > 0 ? v.pNormal : 1;
          let compare_at_price = null;
          
          if (v.pPromo && v.pPromo > 0) {
            price = v.pPromo;
            compare_at_price = v.pNormal;
          }

          return {
            product_id: productId,
            tenant_id: tenantId,
            sku: v.sku,
            price: price,
            compare_at_price: compare_at_price,
            stock_quantity: v.stock,
            attributes: { [v.attrKey]: v.attrVal },
            weight_kg: v.weight,
            length_cm: v.length,
            width_cm: v.width,
            height_cm: v.height,
            image_url: v.vImg
          }
        })

        // Usamos upsert basado en onConflict (tenant_id y sku deben ser unique en DB uc_tenant_sku)
        const { error: varErr } = await supabase.from('product_variations').upsert(varsToUpsert, {
          onConflict: 'tenant_id, sku'
        })

        if (varErr) {
          throw new Error(`Fallo guardando variantes de ${pName}: ${varErr.message}`)
        }
        totalVars += varsToUpsert.length
      }

      setSuccess(`¡Importación exitosa! Se procesaron ${pNames.length} productos con ${totalVars} variantes.`)
      
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
          <select 
            value={selectedCat} 
            onChange={e => setSelectedCat(e.target.value)} 
            className="w-full h-10 px-3 py-2 rounded-md border border-input text-sm bg-background transition-colors focus:ring-2 focus:ring-primary focus:border-transparent"
          >
            <option value="">-- Obligatorio: Seleccionar Categoría --</option>
            {categories.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
          <p className="text-[11px] text-muted-foreground leading-snug pt-1">La plantilla auto-generada asocia los productos directamente a esta categoría.</p>
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
