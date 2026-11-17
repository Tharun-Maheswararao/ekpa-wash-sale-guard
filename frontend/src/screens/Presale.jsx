import { useEffect, useMemo, useState } from 'react'
import { api, money, qty, fmtDate } from '../api.js'
import { Kpi, Message, TypeBadge } from './bits.jsx'

const EFFECT = {
  permanent: { label: 'Lost for good', tone: 'danger' },
  deferred: { label: 'Deferred to basis', tone: 'warn' },
  being_sold: { label: 'Shares being sold', tone: 'muted' },
  used_earlier: { label: 'Already used by an earlier wash', tone: 'muted' },
  no_effect: { label: 'No effect', tone: 'muted' },
}

export default function Presale({ state, asOf, preset, onRecorded }) {
  const holdings = state.holdings
  const keyOf = (h) => `${h.account.id}|${h.ticker}`
  const defaultKey = useMemo(() => {
    if (preset) return keyOf(preset)
    // Start on the taxable holding with the biggest unrealized loss: the one worth checking first.
    const loser = holdings
      .filter((h) => h.account.type === 'taxable' && h.unrealized < 0)
      .sort((a, b) => a.unrealized - b.unrealized)[0]
    return loser ? keyOf(loser) : holdings[0] && keyOf(holdings[0])
  }, [preset, holdings])

  const [key, setKey] = useState(defaultKey)
  const holding = holdings.find((h) => keyOf(h) === key)
  const [quantity, setQuantity] = useState('')
  const [price, setPrice] = useState('')
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  const run = async (q, p) => {
    if (!holding) return
    setBusy(true); setError(null)
    try {
      setResult(await api.presale({
        account_id: holding.account.id, ticker: holding.ticker, sale_date: asOf,
        quantity: q ? Number(q) : null, price: p ? Number(p) : null,
      }))
    } catch (err) {
      setError(err.message); setResult(null)
    } finally {
      setBusy(false)
    }
  }

  const check = (e) => { e.preventDefault(); run(quantity, price) }

  useEffect(() => { setKey(defaultKey) }, [defaultKey])
  // Picking a holding fills in all its shares at today's price and runs the check right away.
  useEffect(() => {
    if (!holding) return
    const q = String(holding.shares)
    const p = String(holding.price ?? '')
    setQuantity(q); setPrice(p)
    run(q, p)
  }, [key, asOf]) // eslint-disable-line react-hooks/exhaustive-deps

  const record = async () => {
    setBusy(true)
    try {
      await api.trade({ account_id: result.account.id, ticker: result.ticker, action: 'SELL',
        quantity: result.quantity, price: result.price, date: result.sale_date })
      onRecorded()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="stack">
      <section className="card">
        <h2>Before you sell</h2>
        <p className="muted small">Pick a holding. You'll see the loss, every purchase of that stock in any account in
          the last 30 days, and how many dollars of the loss those purchases put at risk.</p>
        <form className="form-grid presale-form" onSubmit={check}>
          <label className="span-2">Holding
            <select value={key || ''} onChange={(e) => setKey(e.target.value)}>
              {holdings.map((h) => (
                <option key={keyOf(h)} value={keyOf(h)}>
                  {h.ticker} · {h.account.name} · {qty(h.shares)} sh · {money(h.unrealized)}
                </option>
              ))}
            </select>
          </label>
          <label>Shares to sell<input type="number" step="any" min="0" value={quantity}
            onChange={(e) => setQuantity(e.target.value)} /></label>
          <label>Sale price<input type="number" step="any" min="0" value={price}
            onChange={(e) => setPrice(e.target.value)} /></label>
          <div className="span-2 row gap">
            <button disabled={busy}>{busy ? 'Checking…' : 'Check this sale'}</button>
            <span className="muted small">Sale date {fmtDate(asOf)}</span>
          </div>
        </form>
        {error && <Message level="danger">{error}</Message>}
      </section>

      {result && <Result r={result} onRecord={record} busy={busy} />}
    </div>
  )
}

function Result({ r, onRecord, busy }) {
  const atRisk = r.disallowed
  const dripRisk = r.drip_risks.reduce((s, d) => s + (d.estimated_disallowed || 0), 0)
  return (
    <>
      <section className="kpis">
        <Kpi label={r.is_loss ? 'Loss on this sale' : 'Gain on this sale'} value={money(Math.abs(r.gain_loss))}
          tone={r.is_loss ? 'loss' : 'gain'} hint={`${qty(r.quantity)} sh at ${money(r.price)}`} />
        <Kpi label="Disallowed by recent buys" value={money(atRisk)} tone={r.disallowed_permanent > 0 ? 'danger' : atRisk > 0 ? 'warn' : ''}
          hint={r.disallowed_permanent > 0 ? `${money(r.disallowed_permanent)} lost for good` : atRisk > 0 ? 'Deferred into new basis' : 'Nothing matched'} />
        <Kpi label="Loss you can deduct" value={money(r.is_loss ? -r.allowed_gain_loss : 0)}
          hint={dripRisk > 0 ? `About ${money(dripRisk)} more at risk from reinvestment` : r.is_loss ? 'If you avoid rebuying' : ''} />
        <Kpi label="Safe to rebuy" value={r.rebuy_safe_date ? fmtDate(r.rebuy_safe_date) : 'Any time'}
          hint={r.rebuy_safe_date ? 'In every account, including IRAs' : 'No loss to protect'} />
      </section>

      {r.messages.map((m, i) => <Message key={i} level={m.level}>{m.text}</Message>)}

      <section className="card">
        <h3>Purchases of {r.ticker} in the last 30 days, all accounts</h3>
        {r.recent_purchases.length === 0 ? <p className="muted">None.</p> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Date</th><th>Account</th><th>Type</th><th className="num">Shares</th>
                <th className="num">Price</th><th className="num">Disallowed</th><th>Effect</th></tr></thead>
              <tbody>
                {r.recent_purchases.map((p, i) => (
                  <tr key={i}>
                    <td>{fmtDate(p.date)} <span className="muted small">({p.days_before_sale}d before)</span></td>
                    <td>{p.account.name}</td>
                    <td><TypeBadge type={p.account.type} label={p.account.type_label} /> {p.action === 'REINVEST' && <span className="chip tiny">DRIP</span>}</td>
                    <td className="num">{qty(p.shares)}</td>
                    <td className="num">{money(p.price)}</td>
                    <td className="num">{p.disallowed ? money(p.disallowed) : '—'}</td>
                    <td><span className={`pill ${EFFECT[p.effect].tone}`}>{EFFECT[p.effect].label}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {r.drip_risks.length > 0 && (
        <section className="card">
          <h3>Dividend reinvestment inside the next 30 days</h3>
          <ul className="plain">
            {r.drip_risks.map((d, i) => (
              <li key={i}>
                <strong>{d.account.name}</strong> reinvests {r.ticker}
                {d.pay_date ? ` on ${fmtDate(d.pay_date)} (about ${qty(d.estimated_shares)} sh, ≈ ${money(d.estimated_disallowed)} ${d.permanent ? 'lost for good' : 'deferred'})` : ' (no date on file)'}.
                {' '}Turn it off until {fmtDate(d.turn_off_until)}.
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="card">
        <h3>Lots sold, first in first out</h3>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Bought</th><th className="num">Shares</th><th className="num">Cost basis</th>
              <th className="num">Gain / loss</th><th>Term</th><th className="num">Disallowed</th></tr></thead>
            <tbody>
              {r.lots.map((l, i) => (
                <tr key={i}>
                  <td>{fmtDate(l.acquired)}</td><td className="num">{qty(l.shares)}</td>
                  <td className="num">{money(l.cost_basis)}</td>
                  <td className={`num ${l.gain_loss < 0 ? 'loss' : 'gain'}`}>{money(l.gain_loss)}</td>
                  <td>{l.term}</td><td className="num">{l.disallowed ? money(l.disallowed) : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="row gap top">
          <button className="secondary" onClick={onRecord} disabled={busy}>Record this sale</button>
          <span className="muted small">Adds the sale to the history so the rebuy lock and summary update.</span>
        </div>
      </section>
    </>
  )
}
