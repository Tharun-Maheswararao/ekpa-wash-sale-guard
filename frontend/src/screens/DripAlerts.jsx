import { money, qty, fmtDate } from '../api.js'

const LABEL = { high: 'Act now', medium: 'Watch', ok: 'Clear' }

export default function DripAlerts({ alerts }) {
  if (alerts.length === 0) {
    return <section className="card"><h2>Reinvestment alerts</h2><p className="muted">No account has dividend reinvestment turned on.</p></section>
  }
  return (
    <div className="stack">
      <p className="muted">Automatic dividend reinvestment is a purchase. If it lands within 30 days of a loss sale of the
        same stock, in any account, part of the loss is disallowed. In an IRA that part is lost for good.</p>
      {alerts.map((a, i) => (
        <section key={i} className={`card alert ${a.severity}`}>
          <div className="row between">
            <div>
              <span className={`pill ${a.severity === 'high' ? 'danger' : a.severity === 'medium' ? 'warn' : 'ok'}`}>{LABEL[a.severity]}</span>
              <h3 className="inline">{a.title}</h3>
            </div>
            <div className="muted small">{a.account.name} · {a.account.type_label}</div>
          </div>
          <p>{a.text}</p>
          <div className="kpi-inline">
            <div><span className="muted small">Held</span><strong>{qty(a.held)} sh</strong></div>
            <div><span className="muted small">Next dividend</span><strong>{fmtDate(a.pay_date)}</strong></div>
            <div><span className="muted small">Est. shares bought</span><strong>{qty(a.estimated_shares)}</strong></div>
            <div><span className="muted small">Est. loss affected</span><strong>{money(a.estimated_disallowed)}</strong></div>
          </div>
          {a.action && <div className={`banner ${a.severity === 'high' ? 'danger' : 'warn'}`}>{a.action}</div>}
        </section>
      ))}
    </div>
  )
}
