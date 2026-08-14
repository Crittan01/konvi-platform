import { describe, it, expect, beforeEach, vi } from 'vitest'
import { NextRequest } from 'next/server'

// G20 — tests del proxy /api/ai/index-pending → FastAPI /api/v1/ai/index-pending.
// Cubre: RBAC local (owner/manager), forwarding con Bearer, passthrough de
// {indexed, total} y traducción {detail} → {error}.

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

function post() {
  return POST(new NextRequest('http://localhost:3000/api/ai/index-pending', { method: 'POST' }))
}

beforeEach(() => {
  state.user = OWNER
  state.token = 'tok-test'
  fetchMock.mockReset()
})

describe('/api/ai/index-pending (proxy G20)', () => {
  it('401 sin sesión', async () => {
    state.user = null
    const res = await post()
    expect(res.status).toBe(401)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('403 para operator (rol sin escritura) con el copy que el banner espera', async () => {
    state.user = { id: 'u-2', app_metadata: { tenant_id: 't-1', role: 'operator' } }
    const res = await post()
    expect(res.status).toBe(403)
    expect((await res.json()).error).toMatch(/no tienes permiso/i)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('reenvía al api con Bearer y pasa {indexed, total}', async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ indexed: 3, total: 3 }), { status: 200 }))
    const res = await post()
    expect(res.status).toBe(200)
    expect(await res.json()).toEqual({ indexed: 3, total: 3 })

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toContain('/api/v1/ai/index-pending')
    expect(init.method).toBe('POST')
    expect(init.headers.Authorization).toBe('Bearer tok-test')
  })

  it('429 upstream → {error} traducido conservando el status', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ detail: 'Rate limit excedido para ai.index_pending.' }), { status: 429 })
    )
    const res = await post()
    expect(res.status).toBe(429)
    expect((await res.json()).error).toMatch(/rate limit/i)
  })
})
