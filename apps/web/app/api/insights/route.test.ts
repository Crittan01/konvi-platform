import { describe, it, expect, beforeEach, vi } from 'vitest'
import { NextRequest } from 'next/server'

// G20 — tests del proxy /api/insights → FastAPI /api/v1/insights.
// Cubre: RBAC local (owner/manager), validación de módulo, forwarding con
// Bearer, passthrough del InsightResult, traducción {detail} → {error} y el
// contrato del GET (nunca rompe al panel: fetch caído → {insight: null}).

const state = vi.hoisted(() => ({
  user: null as null | { id: string; app_metadata: Record<string, unknown> },
  token: 'tok-test' as string | null,
}))

vi.mock('@/utils/supabase/server', () => ({
  createClient: async () => ({
    auth: {
      getUser: async () => ({ data: { user: state.user } }),
      getSession: async () => ({
        data: { session: state.token ? { access_token: state.token } : null },
      }),
    },
  }),
}))

const fetchMock = vi.fn()
vi.stubGlobal('fetch', fetchMock)

import { POST, GET } from './route'

const OWNER = { id: 'u-1', app_metadata: { tenant_id: 't-1', role: 'owner' } }

const INSIGHT = {
  resumen: 'Ventas al alza',
  hallazgos: ['h1'],
  acciones: [{ prioridad: 'alta', accion: 'Hacer X' }],
  alerta: null,
  generated_at: '2026-08-14T00:00:00Z',
  tokens_used: 900,
}

function post(body: unknown) {
  return POST(new NextRequest('http://localhost:3000/api/insights', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }))
}

function get(url: string) {
  return GET(new NextRequest(`http://localhost:3000${url}`))
}

beforeEach(() => {
  state.user = OWNER
  state.token = 'tok-test'
  fetchMock.mockReset()
})

describe('/api/insights POST (proxy G20)', () => {
  it('401 sin sesión', async () => {
    state.user = null
    expect((await post({ module: 'orders' })).status).toBe(401)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('403 para operator', async () => {
    state.user = { id: 'u-2', app_metadata: { tenant_id: 't-1', role: 'operator' } }
    expect((await post({ module: 'orders' })).status).toBe(403)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('400 con módulo inválido (no gasta llamada upstream)', async () => {
    const res = await post({ module: 'finanzas' })
    expect(res.status).toBe(400)
    expect((await res.json()).error).toMatch(/módulo no válido/i)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('reenvía al api con Bearer + {module} y pasa el InsightResult', async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify(INSIGHT), { status: 200 }))
    const res = await post({ module: 'orders' })
    expect(res.status).toBe(200)
    expect(await res.json()).toEqual(INSIGHT)

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toContain('/api/v1/insights')
    expect(init.headers.Authorization).toBe('Bearer tok-test')
    expect(JSON.parse(init.body)).toEqual({ module: 'orders' })
  })

  it('traduce {detail} de FastAPI a {error} conservando el status (502)', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ detail: 'Error al consultar Gemini' }), { status: 502 })
    )
    const res = await post({ module: 'metrics' })
    expect(res.status).toBe(502)
    expect((await res.json()).error).toMatch(/gemini/i)
  })
})

describe('/api/insights GET (proxy G20)', () => {
  it('pasa el {insight} del api con el query param intacto', async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ insight: INSIGHT }), { status: 200 }))
    const res = await get('/api/insights?module=inventory')
    expect(res.status).toBe(200)
    expect((await res.json()).insight).toEqual(INSIGHT)
    expect(fetchMock.mock.calls[0][0]).toContain('module=inventory')
  })

  it('400 con módulo inválido', async () => {
    expect((await get('/api/insights?module=nope')).status).toBe(400)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('ante red caída devuelve {insight: null} (el panel cae a idle)', async () => {
    fetchMock.mockRejectedValue(new Error('ECONNREFUSED'))
    const res = await get('/api/insights?module=orders')
    expect(res.status).toBe(200)
    expect(await res.json()).toEqual({ insight: null })
  })
})
