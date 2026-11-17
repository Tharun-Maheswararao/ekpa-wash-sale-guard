import { money, qty, fmtDate } from '../api.js'

export default function RebuyLock({ locks, asOf, alerts }) {
  if (locks.length === 0) {
    return <section className="card"><h2>Rebuy lock</h2><p className="muted">No loss sales in the 30 days before {fmtDate(asOf)}.
      You can buy any stock in any account.</p></section>
  }
  return (
    <div className="stack">
      <p className="muted">After a loss sale, buying the same stock in <em>any</em> account for 30 days disallows the loss.
        These are the dates when buying back becomes safe.</p>
      {locks.map((l) => {
        const drip = alerts.filter((a) => a.ticker === l.ticker && a.severity === 'high')
        return (
          <section key={l.ticker} className="card lock">
            <div className="lock-head">
              <div>
                <div className="ticker">{l.ticker}</div>
                <div className="muted small">{money(l.at_risk)} of loss still at risk ({qty(l.at_risk_shares)} sh)</div>
              </div>
              <div className="lock-date">
                <div className="muted small">Safe to buy from</div>
                <div className="big">{fmtDate(l.safe_date)}</div>
                <div className="countdown">{l.days_left} day{l.days_left === 1 ? '' : 's'} left</div>
              </div>
            </div>
            <div className="lock-accounts">
              {l.accounts.map((a) => (
                <div key={a.id} className={`lock-acct ${a.permanent_if_bought ? 'danger' : 'warn'}`}>
                  <div><strong>{a.name}</strong> <span className="muted small">{a.type_label}</span></div>
                  <div className="small">Don't buy {l.ticker} here before {fmtDate(l.safe_date)}.{' '}
                    {a.permanent_if_bought ? 'A buy here loses the loss for good.' : 'A buy here defers the loss into the new shares.'}</div>
                  {a.drip_on && <div className="small danger-text">Dividend reinvestment is on for {l.ticker} in this account.</div>}
                </div>
              ))}
            </div>
            {drip.map((d, i) => <div key={i} className="banner danger">{d.action}</div>)}
            <details>
              <summary className="small">Loss sales behind this lock</summary>
              <table>
                <thead><tr><th>Sold</th><th>Account</th><th className="num">Shares</th><th className="num">Loss</th>
                  <th className="num">Already disallowed</th><th className="num">At risk</th><th>Clears</th></tr></thead>
                <tbody>
                  {l.sales.map((s, i) => (
                    <tr key={i}><td>{fmtDate(s.date)}</td><td>{s.account.name}</td><td className="num">{qty(s.shares)}</td>
                      <td className="num">{money(s.loss)}</td><td className="num">{money(s.already_disallowed)}</td>
                      <td className="num">{money(s.still_at_risk)}</td><td>{fmtDate(s.safe_date)}</td></tr>
                  ))}
                </tbody>
              </table>
            </details>
          </section>
        )
      })}
    </div>
  )
}
