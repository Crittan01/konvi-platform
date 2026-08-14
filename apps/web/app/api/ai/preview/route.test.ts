import { describe, it, expect, beforeEach, vi } from 'vitest'
import { NextRequest } from 'next/server'

// G20 — tests del proxy /api/ai/preview → FastAPI /api/v1/ai/preview.
// Cubre: validaciones locales (sesión/tenant/mensaje), forwarding con Bearer,
// passthrough de éxito y traducción {detail} → {error} en fallos upstream.

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

import { POST } from './route'

const OWNER = { id: 'u-1', app_metadata: { tenant_id: 't-1', role: 'owner' } }

function post(body: unknown) {
  return POST(new NextRequest('http://localhost:3000/api/ai/preview', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }))
}

function upstreamOk(body: unknown, status = 200) {
  fetchMock.mockResolvedValue(new Response(JSON.stringify(body), { status }))
}

beforeEach(() => {
  state.user = OWNER
  state.token = 'tok-test'
  fetchMock.mockReset()
})

describe('/api/ai/preview (proxy G20)', () => {
  it('401 sin sesión', async () => {
    state.user = null
    const res = await post({ message: 'hola' })
    expect(res.status).toBe(401)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('403 sin tenant', async () => {
    state.user = { id: 'u-1', app_metadata: {} }
    const res = await post({ message: 'hola' })
    expect(res.status).toBe(403)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('400 si el mensaje viene vacío (no gasta llamada upstream)', async () => {
    const res = await post({ message: '   ' })
    expect(res.status).toBe(400)
    expect((await res.json()).error).toMatch(/requerido/i)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('reenvía al api con Bearer + body {message, agent_id} y pasa la respuesta', async () => {
    upstreamOk({ response: 'Hola, sí hacemos envíos.', kb_used: true, kb_count: 2, agent_name: 'Vendedor' })
    const res = await post({ message: ' ¿Envíos a Medellín? ', agent_id: 'ag-9' })
    expect(res.status).toBe(200)
    const data = await res.json()
    expect(data.response).toContain('envíos')
    expect(data.kb_used).toBe(true)

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toContain('/api/v1/ai/preview')
    expect(init.headers.Authorization).toBe('Bearer tok-test')
    expect(JSON.parse(init.body)).toEqual({ message: '¿Envíos a Medellín?', agent_id: 'ag-9' })
  })

  it('omite agent_id si no viene (el api prueba el default)', async () => {
    upstreamOk({ response: 'ok', kb_used: false, kb_count: 0, agent_name: 'X' })
    await post({ message: 'hola' })
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ message: 'hola' })
  })

  it('traduce {detail} de FastAPI a {error} conservando el status (502)', async () => {
    upstreamOk({ detail: 'El modelo no está disponible en este momento.' }, 502)
    const res = await post({ message: 'hola' })
    expect(res.status).toBe(502)
    expect((await res.json()).error).toMatch(/modelo no está disponible/i)
  })

  it('503 si el upstream no responde (red caída)', async () => {
    fetchMock.mockRejectedValue(new Error('ECONNREFUSED'))
    const res = await post({ message: 'hola' })
    expect(res.status).toBe(503)
    expect((await res.json()).error).toMatch(/No se pudo conectar/i)
  })
})
