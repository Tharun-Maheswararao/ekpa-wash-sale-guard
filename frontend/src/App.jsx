import { useCallback, useEffect, useState } from 'react'
import { api } from './api.js'
import Accounts from './screens/Accounts.jsx'
import Presale from './screens/Presale.jsx'
import RebuyLock from './screens/RebuyLock.jsx'
import DripAlerts from './screens/DripAlerts.jsx'
import Summary from './screens/Summary.jsx'

const TABS = [
  { id: 'accounts', label: 'Accounts' },
  { id: 'presale', label: 'Pre-sale check' },
  { id: 'lock', label: 'Rebuy lock' },
  { id: 'drip', label: 'Reinvestment alerts' },
  { id: 'summary', label: 'Summary' },
]

export default function App() {
  const [tab, setTab] = useState('presale')
  const [asOf, setAsOf] = useState(null)
  const [state, setState] = useState(null)
  const [locks, setLocks] = useState([])
  const [alerts, setAlerts] = useState([])
  const [version, setVersion] = useState(0)
  const [error, setError] = useState(null)
  const [preset, setPreset] = useState(null)

  const refresh = useCallback(() => setVersion((v) => v + 1), [])

  useEffect(() => {
    const when = asOf || ''
    Promise.all([api.state(when), api.rebuyLock(when), api.dripAlerts(when)])
      .then(([s, l, a]) => {
        setState(s)
        setLocks(l)
        setAlerts(a)
        if (!asOf) setAsOf(s.as_of)
        setError(null)
      })
      .catch((e) => setError(e.message))
  }, [asOf, version])

  const reset = async () => {
    await api.reset()
    setAsOf(null)
    refresh()
  }

  const badges = {
    lock: locks.length,
    drip: alerts.filter((a) => a.severity === 'high').length,
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="logo" aria-hidden>◆</span>
          <div>
            <div className="brand-name">Wash Sale Guard</div>
            <div className="brand-sub">Ekpa prototype · sample data only</div>
          </div>
        </div>
        <div className="topbar-controls">
          <label className="asof">
            As of
            <input type="date" value={asOf || ''} onChange={(e) => e.target.value && setAsOf(e.target.value)} />
          </label>
          <button className="ghost" onClick={reset} title="Restore the sample accounts">Reset demo</button>
        </div>
      </header>

      <nav className="tabs" role="tablist">
        {TABS.map((t) => (
          <button key={t.id} role="tab" aria-selected={tab === t.id} className={tab === t.id ? 'tab active' : 'tab'}
            onClick={() => setTab(t.id)}>
            {t.label}
            {badges[t.id] > 0 && <span className={`count ${t.id === 'drip' ? 'danger' : ''}`}>{badges[t.id]}</span>}
          </button>
        ))}
      </nav>

      <main>
        {error && <div className="banner danger">{error}</div>}
        {!state ? <p className="muted">Loading…</p> : (
          <>
            {tab === 'accounts' && <Accounts state={state} onChange={refresh}
              onCheck={(h) => { setPreset(h); setTab('presale') }} />}
            {tab === 'presale' && <Presale state={state} asOf={asOf} preset={preset}
              onRecorded={() => { refresh(); setTab('lock') }} />}
            {tab === 'lock' && <RebuyLock locks={locks} asOf={asOf} alerts={alerts} />}
            {tab === 'drip' && <DripAlerts alerts={alerts} />}
            {tab === 'summary' && <Summary asOf={asOf} version={version} />}
          </>
        )}
      </main>

      <footer className="foot">
        Made-up data. Not tax advice. Rules follow IRS Publication 550 for same-ticker stock, first in, first out.
        Rules not yet reviewed by a tax professional.
      </footer>
    </div>
  )
}
