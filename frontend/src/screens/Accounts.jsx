import { useState } from 'react'
import { api, money, qty } from '../api.js'
import { TypeBadge } from './bits.jsx'

export default function Accounts({ state, onChange, onCheck }) {
  return (
    <div className="stack">
      <section className="grid-2">
        {state.accounts.map((a) => {
          const log = state.import_log.find((l) => l.account_id === a.id)
          const rows = state.holdings.filter((h) => h.account.id === a.id)
          const value = rows.reduce((s, h) => s + (h.market_value || 0), 0)
          return (
            <div key={a.id} className="card">
              <div className="row between">
                <div>
                  <h3>{a.name}</h3>
                  <div className="muted small">{a.id} · {a.broker} format</div>
                </div>
                <TypeBadge type={a.type} label={a.type_label} />
              </div>
              <div className="kpi-inline">
                <div><span className="muted small">Market value</span><strong>{money(value)}</strong></div>
                <div><span className="muted small">Positions</span><strong>{rows.length}</strong></div>
                <div><span className="muted small">Reinvesting</span><strong>{a.drip_tickers.join(', ') || 'None'}</strong></div>
              </div>
              {log && <div className="muted small">Imported {log.imported} trades from {log.file}
                {log.skipped ? `, skipped ${log.skipped} cash or out-of-scope rows` : ''}.</div>}
            </div>
          )
        })}
      </section>

      <section className="card">
        <h2>Holdings</h2>
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>Account</th><th>Ticker</th><th className="num">Shares</th><th className="num">Basis</th>
                <th className="num">Wash adj.</th><th className="num">Price</th><th className="num">Unrealized</th><th /></tr>
            </thead>
            <tbody>
              {state.holdings.map((h) => (
                <tr key={h.account.id + h.ticker}>
                  <td>{h.account.name}</td>
                  <td><strong>{h.ticker}</strong>{h.drip_on && <span className="chip tiny">DRIP</span>}</td>
                  <td className="num">{qty(h.shares)}</td>
                  <td className="num">{money(h.basis)}</td>
                  <td className="num">{h.wash_adjustment ? <span className="warn-text">+{money(h.wash_adjustment)}</span> : '—'}</td>
                  <td className="num">{money(h.price)}</td>
                  <td className={`num ${h.unrealized < 0 ? 'loss' : 'gain'}`}>{money(h.unrealized)}</td>
                  <td className="num">
                    {h.account.type === 'taxable' && h.unrealized < 0 &&
                      <button className="link" onClick={() => onCheck(h)}>Check sale →</button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="muted small">"Wash adj." is a disallowed loss carried into these shares' cost basis.</p>
      </section>

      <Upload formats={state.formats} onDone={onChange} />
    </div>
  )
}

function Upload({ formats, onDone }) {
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true); setError(null); setResult(null)
    try {
      const r = await api.upload(new FormData(e.currentTarget))
      setResult(r)
      onDone()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="card">
      <h2>Upload a broker history file</h2>
      <p className="muted small">For brokers Ekpa can't connect to. Each format has its own converter into one common format.
        Use made-up files only.</p>
      <form className="form-grid" onSubmit={submit}>
        <label>CSV file<input type="file" name="file" accept=".csv,text/csv" required /></label>
        <label>Account name<input name="account_name" placeholder="Roth IRA" required /></label>
        <label>Account type
          <select name="account_type" defaultValue="taxable">
            <option value="taxable">Taxable</option>
            <option value="ira">Traditional IRA</option>
            <option value="roth_ira">Roth IRA</option>
          </select>
        </label>
        <label>Broker format
          <select name="broker_format" defaultValue="auto">
            <option value="auto">Detect automatically</option>
            {formats.map((f) => <option key={f.id} value={f.id}>{f.label}</option>)}
          </select>
        </label>
        <label className="span-2">Tickers with dividend reinvestment on
          <input name="drip_tickers" placeholder="KO, PFE" />
        </label>
        <div className="span-2"><button disabled={busy}>{busy ? 'Importing…' : 'Import'}</button></div>
      </form>
      {error && <div className="banner danger">{error}</div>}
      {result && (
        <div className="banner ok">
          Imported {result.imported} trades into <strong>{result.account.name}</strong> ({result.format} format).
          {result.skipped.length > 0 && (
            <details><summary>{result.skipped.length} rows skipped</summary>
              <ul className="small">{result.skipped.map((s) => <li key={s.row}>Row {s.row}: {s.reason}</li>)}</ul>
            </details>
          )}
        </div>
      )}
    </section>
  )
}

