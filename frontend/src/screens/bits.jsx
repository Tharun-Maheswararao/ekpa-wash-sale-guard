export function TypeBadge({ type, label }) {
  return <span className={`badge ${type === 'taxable' ? 'taxable' : 'ira'}`}>{label}</span>
}

export function Kpi({ label, value, tone, hint }) {
  return (
    <div className={`kpi ${tone || ''}`}>
      <div className="kpi-label">{label}</div>
      <div className="kpi-value">{value}</div>
      {hint && <div className="kpi-hint">{hint}</div>}
    </div>
  )
}

export function Message({ level, children }) {
  return <div className={`banner ${level}`}>{children}</div>
}
