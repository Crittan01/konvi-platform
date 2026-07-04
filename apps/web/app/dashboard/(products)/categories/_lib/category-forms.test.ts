import { describe, it, expect } from 'vitest'
import { slugify, parseAllowedValues } from './category-forms'

describe('slugify', () => {
  it('minúsculas + guion bajo por espacios', () => {
    expect(slugify('Aceites Esenciales')).toBe('aceites_esenciales')
  })
  it('elimina acentos y diacríticos', () => {
    expect(slugify('Jabón Artesanal')).toBe('jabon_artesanal')
    expect(slugify('Nutrición Ñam')).toBe('nutricion_nam')
  })
  it('colapsa separadores y recorta bordes', () => {
    expect(slugify('  Salud   &   Belleza!! ')).toBe('salud_belleza')
  })
  it('label sin caracteres válidos → cadena vacía (la UI lo rechaza)', () => {
    expect(slugify('!!! ??? ')).toBe('')
    expect(slugify('   ')).toBe('')
  })
  it('preserva dígitos', () => {
    expect(slugify('Kit 2x1')).toBe('kit_2x1')
  })
})

describe('parseAllowedValues', () => {
  it('select → lista de strings recortados', () => {
    expect(parseAllowedValues('select', 'Lavanda, Menta ,  Coco')).toEqual(['Lavanda', 'Menta', 'Coco'])
  })
  it('metric → castea tokens numéricos a Number', () => {
    expect(parseAllowedValues('metric', '5, 10, 30, 50')).toEqual([5, 10, 30, 50])
  })
  it('number → castea a Number', () => {
    expect(parseAllowedValues('number', '15, 30, 50')).toEqual([15, 30, 50])
  })
  it('metric con token no numérico → lo deja como string', () => {
    expect(parseAllowedValues('metric', '5, grande, 10')).toEqual([5, 'grande', 10])
  })
  it('boolean/text → siempre lista vacía (no hay lista cerrada)', () => {
    expect(parseAllowedValues('boolean', 'Sí, No')).toEqual([])
    expect(parseAllowedValues('text', 'lo que sea')).toEqual([])
  })
  it('descarta tokens vacíos (comas colgantes)', () => {
    expect(parseAllowedValues('select', 'A, , B, ')).toEqual(['A', 'B'])
  })
  it('cadena vacía → lista vacía', () => {
    expect(parseAllowedValues('select', '')).toEqual([])
    expect(parseAllowedValues('metric', '   ')).toEqual([])
  })
})
