async function request(path, options = {}) {
  const res = await fetch(`/api${path}`, options)
  const body = await res.json().catch(() => ({}))
  if (!res.ok) {
    const detail = Array.isArray(body.detail) ? body.detail.map((d) => d.msg).join('; ') : body.detail
    throw new Error(detail || `Request failed (${res.status})`)
  }
  return body
}

const json = (data) => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(data),
})

const query = (params) => {
  const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v != null && v !== ''))
  return q.toString() ? `?${q}` : ''
}

export const api = {
  state: (asOf) => request(`/state${query({ as_of: asOf })}`),
  presale: (data) => request('/presale-check', json(data)),
  trade: (data) => request('/trades', json(data)),
  rebuyLock: (asOf) => request(`/rebuy-lock${query({ as_of: asOf })}`),
  dripAlerts: (asOf) => request(`/drip-alerts${query({ as_of: asOf })}`),
  summary: (year, asOf) => request(`/summary${query({ year, as_of: asOf })}`),
  upload: (form) => request('/upload', { method: 'POST', body: form }),
  reset: () => request('/reset', { method: 'POST' }),
}

const usd = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' })
export const money = (n) => (n == null ? '—' : usd.format(n))
export const qty = (n) => (n == null ? '—' : Number(n).toLocaleString('en-US', { maximumFractionDigits: 4 }))
export const fmtDate = (iso) =>
  iso ? new Date(`${iso}T00:00:00`).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }) : '—'
