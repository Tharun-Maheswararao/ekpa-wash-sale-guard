import { useEffect, useState } from 'react'
import { api, money, qty, fmtDate } from '../api.js'
import { Kpi, TypeBadge } from './bits.jsx'

export default function Summary({ asOf, version }) {
  const year = Number(asOf.slice(0, 4))
  const [s, setS] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    api.summary(year, asOf).then(setS).catch((e) => setError(e.message))
  }, [year, asOf, version])

  if (error) return <div className="banner danger">{error}</div>
  if (!s) return <p className="muted">Loading…</p>

  return (
    <div className="stack">
      <section className="kpis">
        <Kpi label={`Losses realized in ${s.year}`} value={money(s.total_losses)} tone="loss" hint={`Gains ${money(s.total_gains)}`} />
        <Kpi label="Disallowed by wash sales" value={money(s.disallowed)} tone="warn" hint={`${s.wash_sale_count} wash sales`} />
        <Kpi label="Lost for good (IRA buys)" value={money(s.disallowed_permanent)} tone="danger" hint="Never deductible" />
        <Kpi label="Deferred into new basis" value={money(s.disallowed_deferred)} hint="Deductible when those shares are sold" />
      </section>

      <section className="card">
        <h2>By account</h2>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Account</th><th>Type</th><th className="num">Losses sold here</th><th className="num">Disallowed</th>
              <th className="num">Lost for good</th><th className="num">Disallowed by buys here</th></tr></thead>
            <tbody>
              {s.by_account.map((a) => (
                <tr key={a.id}><td>{a.name}</td><td><TypeBadge type={a.type} label={a.type_label} /></td>
                  <td className="num">{money(a.loss)}</td><td className="num">{money(a.disallowed)}</td>
                  <td className="num">{money(a.permanent)}</td><td className="num">{money(a.caused_by_purchases_here)}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="card">
        <h2>Every loss sale in {s.year}</h2>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Sold</th><th>Ticker</th><th>From</th><th className="num">Loss</th><th className="num">Disallowed</th>
              <th className="num">Deductible</th><th>Triggered by</th></tr></thead>
            <tbody>
              {s.events.map((e, i) => (
                <tr key={i}>
                  <td>{fmtDate(e.date)}</td><td><strong>{e.ticker}</strong></td><td>{e.account.name}</td>
                  <td className="num loss">{money(e.loss)}</td>
                  <td className="num">{e.disallowed ? money(e.disallowed) : '—'}</td>
                  <td className="num">{money(e.allowed_loss)}</td>
                  <td>
                    {e.replacements.length === 0 ? <span className="pill ok">Clean</span> :
                      e.replacements.map((r, j) => (
                        <div key={j} className="small">
                          <span className={`pill ${r.permanent ? 'danger' : 'warn'}`}>{r.permanent ? 'Lost' : 'Deferred'}</span>{' '}
                          {money(r.disallowed)} · {r.action === 'REINVEST' ? 'reinvested' : 'bought'} {qty(r.shares)} sh in {r.account.name} on {fmtDate(r.date)}
                        </div>
                      ))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
