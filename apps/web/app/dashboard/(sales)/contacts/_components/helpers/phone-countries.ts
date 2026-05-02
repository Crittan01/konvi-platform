/**
 * Rev. 103 — Phone country codes y formato display.
 *
 * Sincronizado con SUPPORTED_COUNTRY_CODES en
 * apps/web/.../contacts/page.tsx (server action). Sin emoji de bandera:
 * muchos OS (Windows en particular) no las renderizan y se ven como
 * caracteres rotos.
 */

export type PhoneCountryMeta = {
  code: string
  label: string
  placeholderDigits: string
}

export const PHONE_COUNTRIES: PhoneCountryMeta[] = [
  { code: '57',  label: 'Colombia',  placeholderDigits: '3001234567' },
  { code: '58',  label: 'Venezuela', placeholderDigits: '4141234567' },
  { code: '593', label: 'Ecuador',   placeholderDigits: '991234567' },
  { code: '51',  label: 'Perú',      placeholderDigits: '912345678' },
  { code: '52',  label: 'México',    placeholderDigits: '5512345678' },
  { code: '1',   label: 'USA/CA',    placeholderDigits: '5551234567' },
  { code: '34',  label: 'España',    placeholderDigits: '612345678' },
  { code: '54',  label: 'Argentina', placeholderDigits: '91123456789' },
  { code: '56',  label: 'Chile',     placeholderDigits: '912345678' },
  { code: '55',  label: 'Brasil',    placeholderDigits: '11912345678' },
]

/**
 * Display-friendly del phone E.164. Espacia el prefijo conocido del resto.
 * Para Colombia (12 dígitos totales) particiona como +57 XXX XXX XXXX.
 */
export const formatPhone = (raw: string): string => {
  const digits = (raw || '').replace(/\D/g, '')
  if (!digits) return raw || ''
  if (digits.startsWith('57') && digits.length === 12) {
    return `+57 ${digits.slice(2, 5)} ${digits.slice(5, 8)} ${digits.slice(8)}`
  }
  // Detectar prefijo iterando de más largo a más corto (evita match
  // prematuro de +1 cuando el número arranca con 193).
  const prefixes = ['593', '52', '54', '55', '56', '51', '57', '58', '34', '1']
  for (const p of prefixes) {
    if (digits.startsWith(p) && digits.length >= p.length + 7) {
      return `+${p} ${digits.slice(p.length)}`
    }
  }
  return `+${digits}`
}
