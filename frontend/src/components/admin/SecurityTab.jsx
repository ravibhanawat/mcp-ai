import { useEffect, useState } from 'react'
import { apiJson } from '../../lib/api'

export default function SecurityTab() {
  const [policy, setPolicy] = useState(null)
  const [models, setModels] = useState([])
  const [providers, setProviders] = useState([])
  const [error, setError] = useState('')

  useEffect(() => {
    (async () => {
      try {
        const policyData = await apiJson('/admin/ai/policy')
        const modelsData = await apiJson('/admin/ai/models')
        const providersData = await apiJson('/admin/ai/providers')

        setPolicy(policyData)
        setModels(modelsData)
        setProviders(providersData)
      } catch (e) { setError(e.message) }
    })()
  }, [])

  const toggleUserSelection = async (enabled) => {
    if (!policy) return
    setError('')
    try {
      setPolicy(p => ({ ...p, allow_user_selection: enabled }))
      await apiJson('/admin/ai/policy', {
        method: 'PUT',
        body: JSON.stringify({ ...policy, allow_user_selection: enabled })
      })
    } catch (e) {
      setError(e.message)
      setPolicy(p => ({ ...p, allow_user_selection: !enabled }))
    }
  }

  if (!policy) {
    return <div style={{ padding: '16px', color: 'var(--text-muted)' }}>Loading…</div>
  }

  const activeModels = models.filter(m => m.is_active)

  return (
    <>
      {error && <div className="form-error">{error}</div>}

      {/* User Model Selection */}
      <div className="form-panel">
        <strong style={{ display: 'block', marginBottom: 12 }}>User Model Selection</strong>
        <label className="checkbox">
          <input type="checkbox" checked={policy.allow_user_selection || false}
                 onChange={e => toggleUserSelection(e.target.checked)} />
          Allow users to select models
        </label>
        <span className="field-hint">
          When off, every user gets the model configured for their request's purpose and cannot change it.
          Users can never override this by asking the assistant.
        </span>
      </div>

      {/* Selectable Models */}
      <div className="form-panel">
        <strong style={{ display: 'block', marginBottom: 12 }}>Selectable Models</strong>
        {!policy.allow_user_selection && (
          <div className="form-warning">
            Model selection is disabled. Enable it above to allow users to choose models.
          </div>
        )}
        {policy.allow_user_selection && activeModels.length === 0 && (
          <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>No active models available.</div>
        )}
        {policy.allow_user_selection && activeModels.length > 0 && (
          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 8 }}>
            Per-model selection is configured at the tenant level and not yet editable here.
            The following active models are available:
          </div>
        )}
        {policy.allow_user_selection && activeModels.length > 0 && (
          <table className="dt-table" style={{ marginTop: 8 }}>
            <thead>
              <tr>
                <th>Model</th><th>Provider</th><th>Purpose</th>
              </tr>
            </thead>
            <tbody>
              {activeModels.map(m => (
                <tr key={m.id}>
                  <td>{m.model_name}</td>
                  <td>{m.provider_name}</td>
                  <td>{m.purpose}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Data Egress */}
      <div className="form-panel">
        <strong style={{ display: 'block', marginBottom: 12 }}>Data Egress Policy</strong>
        {providers.length === 0 ? (
          <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>No providers configured.</div>
        ) : (
          <table className="dt-table">
            <thead>
              <tr>
                <th>Provider</th><th>Egress Class</th><th>SAP Data Permitted</th>
              </tr>
            </thead>
            <tbody>
              {providers.map(p => (
                <tr key={p.id}>
                  <td>{p.name}</td>
                  <td><span className={`pill pill-${p.egress_class}`}>{p.egress_class}</span></td>
                  <td>{p.sap_data_permitted ? 'Yes' : 'No'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <span className="field-hint" style={{ display: 'block', marginTop: 12 }}>
          SAP record payloads sent to external providers are redacted unless that provider is
          explicitly permitted. Enabling that permission is audited.
        </span>
      </div>
    </>
  )
}
