import type { Health, ImportBatch, Instrument, Portfolio, Position } from './types'

/** Remonte le message d'erreur du backend plutôt qu'un « 500 » opaque. */
async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)

  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`
    try {
      const body = await response.json()
      if (body?.detail) detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch {
      // Réponse non-JSON : on garde le statut HTTP.
    }
    throw new Error(detail)
  }

  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export const api = {
  health: () => request<Health>('/api/health'),

  getPortfolio: () => request<Portfolio>('/api/portfolio'),

  importXtbFile: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<ImportBatch>('/api/imports/xtb', { method: 'POST', body: form })
  },

  listImports: () => request<ImportBatch[]>('/api/imports'),

  createManualPosition: (payload: {
    broker_symbol: string
    quantity: number
    avg_price: number
    currency?: string | null
    comment?: string | null
  }) =>
    request<Position>('/api/portfolio/positions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  deletePosition: (id: number) =>
    request<void>(`/api/portfolio/positions/${id}`, { method: 'DELETE' }),

  setSymbolOverride: (payload: { broker_symbol: string; provider_symbol: string; note?: string }) =>
    request<Instrument>('/api/portfolio/symbol-overrides', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
}
