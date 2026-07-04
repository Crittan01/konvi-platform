// @vitest-environment jsdom
import { describe, it, expect } from 'vitest'
import type React from 'react'
import {
  wrapSelection,
  prefixLine,
  prefixLineNumbered,
  insertAtCursor,
} from './editor'

// Construye un textarea real (jsdom) + un ref-like + un capturador de setText.
function setup(value: string, selStart: number, selEnd: number) {
  const ta = document.createElement('textarea')
  ta.value = value
  document.body.appendChild(ta)
  ta.setSelectionRange(selStart, selEnd)
  const ref = { current: ta } as React.RefObject<HTMLTextAreaElement | null>
  let out = ''
  const setText = (v: string) => { out = v }
  return { ref, setText, getOut: () => out }
}

describe('wrapSelection', () => {
  it('envuelve la selección con el marker', () => {
    const { ref, setText, getOut } = setup('hola mundo', 0, 4)
    wrapSelection(ref, setText, '*')
    expect(getOut()).toBe('*hola* mundo')
  })

  it('sin selección inserta el placeholder "texto" envuelto', () => {
    const { ref, setText, getOut } = setup('', 0, 0)
    wrapSelection(ref, setText, '_')
    expect(getOut()).toBe('_texto_')
  })
})

describe('prefixLine', () => {
  it('prefija todas las líneas seleccionadas', () => {
    const { ref, setText, getOut } = setup('a\nb', 0, 3)
    prefixLine(ref, setText, '> ')
    expect(getOut()).toBe('> a\n> b')
  })

  it('prefija solo la línea del cursor cuando no hay selección', () => {
    const { ref, setText, getOut } = setup('uno\ndos', 5, 5)
    prefixLine(ref, setText, '* ')
    expect(getOut()).toBe('uno\n* dos')
  })
})

describe('prefixLineNumbered', () => {
  it('numera cada línea desde 1', () => {
    const { ref, setText, getOut } = setup('a\nb\nc', 0, 5)
    prefixLineNumbered(ref, setText)
    expect(getOut()).toBe('1. a\n2. b\n3. c')
  })
})

describe('insertAtCursor', () => {
  it('inserta el texto en la posición del cursor', () => {
    const { ref, setText, getOut } = setup('ab', 1, 1)
    insertAtCursor(ref, setText, 'X')
    expect(getOut()).toBe('aXb')
  })

  it('reemplaza la selección activa', () => {
    const { ref, setText, getOut } = setup('abc', 0, 2)
    insertAtCursor(ref, setText, '😀')
    expect(getOut()).toBe('😀c')
  })
})
