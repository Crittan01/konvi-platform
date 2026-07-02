// F2 (roadmap producción) — jerarquía de categorías Categoría › Subcategoría (2 niveles).
//
// Módulo PURO (sin React) que transforma la lista plana de categorías (id, display_label, parent_id)
// en grupos para un <select> con <optgroup>. Regla de negocio: los PRODUCTOS cuelgan de HOJAS
// (subcategorías); una categoría con hijos es un ENCABEZADO (optgroup label) y NO es seleccionable.
//
// Backward-compatible: una categoría raíz SIN hijos sigue siendo una hoja seleccionable (grupo sin
// etiqueta = <option> de primer nivel). Así el catálogo plano actual funciona idéntico hasta que se
// creen los padres y se enlacen las categorías.

export interface FlatCategory {
  id: string
  display_label: string
  parent_id?: string | null
}

export interface CategoryPickerOption {
  id: string
  display_label: string
}

export interface CategoryPickerGroup {
  /** Etiqueta del <optgroup>; null = opciones de primer nivel (sin agrupar). */
  label: string | null
  options: CategoryPickerOption[]
}

const pick = (c: FlatCategory): CategoryPickerOption => ({ id: c.id, display_label: c.display_label })

/**
 * Construye los grupos del picker preservando el orden de entrada (ya viene ordenado por
 * sort_order → display_label desde la query). Los grupos etiquetados (padres con hijos) van
 * primero, en orden de sus raíces; las hojas sueltas (raíces sin hijos) caen en un grupo sin
 * etiqueta al final. Solo se listan HOJAS como opciones seleccionables.
 */
export function buildCategoryPicker(cats: FlatCategory[]): CategoryPickerGroup[] {
  const byParent = new Map<string | null, FlatCategory[]>()
  const hasChildren = new Set<string>()
  for (const c of cats) {
    const p = c.parent_id ?? null
    if (!byParent.has(p)) byParent.set(p, [])
    byParent.get(p)!.push(c)
    if (p) hasChildren.add(p)
  }

  const groups: CategoryPickerGroup[] = []

  // Toda categoría con hijos → <optgroup> etiquetado con sus HOJAS directas (defensivo ante >2 niveles:
  // un hijo que a su vez tenga nietos se trata como encabezado, no como opción). Preserva orden de entrada.
  for (const c of cats) {
    if (!hasChildren.has(c.id)) continue
    const leaves = (byParent.get(c.id) ?? []).filter((k) => !hasChildren.has(k.id))
    if (leaves.length) groups.push({ label: c.display_label, options: leaves.map(pick) })
  }

  // Raíces sin hijos → hojas sueltas (grupo sin etiqueta), al final.
  const standalone = (byParent.get(null) ?? []).filter((r) => !hasChildren.has(r.id))
  if (standalone.length) groups.push({ label: null, options: standalone.map(pick) })

  return groups
}

/** Conjunto de ids que son HOJAS (seleccionables). Útil para validar una selección persistida. */
export function leafCategoryIds(cats: FlatCategory[]): Set<string> {
  const hasChildren = new Set<string>()
  for (const c of cats) if (c.parent_id) hasChildren.add(c.parent_id)
  return new Set(cats.filter((c) => !hasChildren.has(c.id)).map((c) => c.id))
}
