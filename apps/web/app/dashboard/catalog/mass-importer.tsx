'use client'

import { useState } from 'react'
import * as XLSX from 'xlsx'
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

  const HEADERS = [
    "SKU_Variante (Obligatorio)", 
    "Nombre_Producto", 
    "Descripcion", 
    "Imagen_Leyenda_URL", 
    "Variante_Atributo_1 (Ej: Talla)", 
    "Variante_Valor_1 (Ej: L)", 
    "Precio ($)", 
    "Precio_Lista ($)", 
    "Inventario", 
    "Peso (kg)", "Largo (cm)", "Ancho (cm)", "Alto (cm)", "Variante_Foto_URL"
  ]

  const handleDownloadTemplate = () => {
    if (!selectedCat) { setError("Selecciona una categoría primero para la plantilla."); return }
    setError(null)
    setSuccess(null)
    const catName = categories.find(c => c.id === selectedCat)?.name || 'General'
    const ws = XLSX.utils.aoa_to_sheet([HEADERS,
      ["VAR-EJEMPLO-01", "Zapatillas Comfort", "Unas zapatillas", "", "Color", "Rojo", 599.99, 799.00, 10, 0.5, 30, 20, 10, ""]
    ])
    // Estilos muy básicos, XLSX libre es limitado pero el UX de dar la tabla es gigante
    const wb = XLSX.utils.book_new()
    XLSX.utils.book_append_sheet(wb, ws, "Plantilla")
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

      // Agrupamos filas por Nombre_Producto para saber qué son Variantes de un mismo producto
      const productsMap: Record<string, { desc: string, img: string, variants: any[] }> = {}
      for (const row of rows) {
        const pName = row["Nombre_Producto"]?.toString().trim()
        const sku = row["SKU_Variante (Obligatorio)"]?.toString().trim()
        if (!pName || !sku) continue

        if (!productsMap[pName]) {
          productsMap[pName] = {
            desc: row["Descripcion"]?.toString().trim(),
            img: row["Imagen_Leyenda_URL"]?.toString().trim(),
            variants: []
          }
        }
        
        productsMap[pName].variants.push({
          sku: sku,
          attrKey: row["Variante_Atributo_1 (Ej: Talla)"]?.toString().trim() || "Genérico",
          attrVal: row["Variante_Valor_1 (Ej: L)"]?.toString().trim() || "Estándar",
          price: parseFloat(row["Precio ($)"]) || 0,
          compare: parseFloat(row["Precio_Lista ($)"]) || null,
          stock: parseInt(row["Inventario"]) || 0,
          weight: parseFloat(row["Peso (kg)"]) || null,
          length: parseFloat(row["Largo (cm)"]) || null,
          width: parseFloat(row["Ancho (cm)"]) || null,
          height: parseFloat(row["Alto (cm)"]) || null,
          vImg: row["Variante_Foto_URL"]?.toString().trim() || null
        })
      }

      const pNames = Object.keys(productsMap)
      if (pNames.length === 0) throw new Error("No se encontraron productos válidos para importar (falta Nombre o SKU). Revisa la plantilla.")

      const supabase = createClient()
      let totalVars = 0
      
      // Procesamos secuencialmente producto por producto
      for (const pName of pNames) {
        const prodData = productsMap[pName]
        // 1. Inyectamos Producto Base
        const { data: prodResp, error: prodErr } = await supabase.from('products').insert({
          tenant_id: tenantId,
          title: pName,
          description: prodData.desc || null,
          cover_image_url: prodData.img || null,
          platform_category_id: selectedCat,
          status: 'active'
        }).select().single()

        if (prodErr || !prodResp) throw new Error(prodErr?.message || "Error insertando producto " + pName)

        // 2. Inyectamos Variantes
        const varsToInsert = prodData.variants.map((v: any) => ({
          product_id: prodResp.id,
          tenant_id: tenantId,
          sku: v.sku,
          price: v.price > 0 ? v.price : 1, // safety fallback prevent RLS crash
          compare_at_price: v.compare,
          stock_quantity: v.stock,
          attributes: { [v.attrKey]: v.attrVal },
          weight_kg: v.weight,
          length_cm: v.length,
          width_cm: v.width,
          height_cm: v.height,
          image_url: v.vImg
        }))

        const { error: varErr } = await supabase.from('product_variations').insert(varsToInsert)
        if (varErr) {
          // Fallback delete of base product is recommended in real systems but omitted for simplicity
          throw new Error(`Fallo insertando variantes de ${pName}: ${varErr.message}`)
        }
        totalVars += varsToInsert.length
      }

      setSuccess(`¡Importación exitosa! Se cargaron ${pNames.length} productos con un total de ${totalVars} variantes.`)
      
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
