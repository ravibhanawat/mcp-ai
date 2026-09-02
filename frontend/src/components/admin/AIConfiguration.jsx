import { useState } from 'react'
import ProvidersTab from './ProvidersTab'
import ModelsTab from './ModelsTab'
import RoutingTab from './RoutingTab'
import FallbackTab from './FallbackTab'
import SecurityTab from './SecurityTab'

const TABS = [
  { id: 'providers', label: 'Providers', Component: ProvidersTab },
  { id: 'models',    label: 'Models',    Component: ModelsTab },
  { id: 'routing',   label: 'Routing',   Component: RoutingTab },
  { id: 'fallback',  label: 'Fallback',  Component: FallbackTab },
  { id: 'security',  label: 'Security',  Component: SecurityTab },
]

// Sub-tabs live here rather than in SettingsModal so App.jsx does not grow
// another nine branches.
export default function AIConfiguration() {
  const [tab, setTab] = useState('providers')
  const Active = TABS.find(t => t.id === tab).Component
  return (
    <div className="ai-config">
      <div className="modal-tabs modal-tabs-nested">
        {TABS.map(t => (
          <button
            key={t.id}
            className={`modal-tab ${tab === t.id ? 'active' : ''}`}
            onClick={() => setTab(t.id)}
          >{t.label}</button>
        ))}
      </div>
      <div className="ai-config-body"><Active /></div>
    </div>
  )
}
