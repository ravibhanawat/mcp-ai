import { useEffect, useState } from 'react'
import { apiJson } from '../../lib/api'

const UNCHANGED = '••••••••'

const BLANK = {
  name: '', provider_type: 'OLLAMA', base_url: '', organization_id: '',
  deployment_name: '', timeout_seconds: 30, max_retries: 2,
  sap_data_permitted: false, is_active: true, api_key: '',
}

export default function ProvidersTab() {
  const [providers, setProviders] = useState([])
  const [types, setTypes] = useState([])
  const [editing, setEditing] = useState(null)
  const [testing, setTesting] = useState({})
  const [error, setError] = useState('')

  const load = async () => {
    try {
      setProviders(await apiJson('/admin/ai/providers'))
      const { provider_types } = await apiJson('/admin/ai/provider-types')
      setTypes(provider_types)
    } catch (e) { setError(e.message) }
  }
  useEffect(() => { load() }, [])

  const save = async () => {
    setError('')
    const path = editing.id ? `/admin/ai/providers/${editing.id}` : '/admin/ai/providers'
    try {
      await apiJson(path, {
        method: editing.id ? 'PATCH' : 'POST',
        body: JSON.stringify(editing),
      })
      setEditing(null)
      load()
    } catch (e) { setError(e.message) }
  }

  const test = async (id) => {
    setTesting(t => ({ ...t, [id]: { status: 'testing' } }))
    try {
      const result = await apiJson(`/admin/ai/providers/${id}/test`, { method: 'POST' })
      setTesting(t => ({ ...t, [id]: result }))
    } catch (e) {
      setTesting(t => ({ ...t, [id]: { status: 'error', error: e.message } }))
    }
  }

  const remove = async (id) => {
    if (!confirm('Delete this provider and every model that uses it?')) return
    try { await apiJson(`/admin/ai/providers/${id}`, { method: 'DELETE' }); load() }
    catch (e) { setError(e.message) }
  }

  return (
    <>
      {error && <div className="form-error">{error}</div>}

      <table className="dt-table">
        <thead>
          <tr>
            <th>Provider</th><th>Type</th><th>Endpoint</th><th>Data egress</th>
            <th>Credential</th><th>Status</th><th></th>
          </tr>
        </thead>
        <tbody>
          {providers.map(p => (
            <tr key={p.id}>
              <td>{p.name}</td>
              <td>{p.provider_type}</td>
              <td className="mono">{p.base_url || '—'}</td>
              <td>
                <span className={`pill pill-${p.egress_class}`}>{p.egress_class}</span>
                {p.sap_data_permitted && <span className="pill pill-warn">SAP data permitted</span>}
              </td>
              <td className="mono">{p.credential_masked || '—'}</td>
              <td>
                {testing[p.id]
                  ? (testing[p.id].status === 'healthy'
                      ? `Connected · ${testing[p.id].latency_ms} ms`
                      : testing[p.id].error || testing[p.id].status)
                  : (p.is_active ? 'Active' : 'Inactive')}
              </td>
              <td className="row-actions">
                <button className="btn-ghost" onClick={() => test(p.id)}>Test</button>
                <button className="btn-ghost" onClick={() => setEditing({ ...p, api_key: UNCHANGED })}>Edit</button>
                <button className="btn-ghost danger" onClick={() => remove(p.id)}>Delete</button>
              </td>
            </tr>
          ))}
          {providers.length === 0 && (
            <tr><td colSpan={7} className="empty">
              No providers configured. Add one to give the assistant a model.
            </td></tr>
          )}
        </tbody>
      </table>

      <button className="btn-primary" onClick={() => setEditing({ ...BLANK })}>Add provider</button>

      {editing && (
        <div className="form-panel">
          <label>Name
            <input value={editing.name} onChange={e => setEditing({ ...editing, name: e.target.value })} />
          </label>
          <label>Type
            <select value={editing.provider_type}
                    onChange={e => setEditing({ ...editing, provider_type: e.target.value })}>
              {types.map(t => <option key={t} value={t}>{t}</option>)}
            </select>
          </label>
          <label>Base URL
            <input value={editing.base_url}
                   onChange={e => setEditing({ ...editing, base_url: e.target.value })} />
          </label>
          {editing.provider_type === 'AZURE_OPENAI' && (
            <label>Deployment name
              <input value={editing.deployment_name || ''}
                     onChange={e => setEditing({ ...editing, deployment_name: e.target.value })} />
            </label>
          )}
          <label>API key
            <input type="password" value={editing.api_key}
                   onChange={e => setEditing({ ...editing, api_key: e.target.value })} />
            <span className="field-hint">
              Leave as {UNCHANGED} to keep the stored key. Keys are encrypted at rest and
              never shown again after saving.
            </span>
          </label>
          <label>Timeout (seconds)
            <input type="number" min="1" max="600" value={editing.timeout_seconds}
                   onChange={e => setEditing({ ...editing, timeout_seconds: Number(e.target.value) })} />
          </label>
          <label className="checkbox">
            <input type="checkbox" checked={editing.sap_data_permitted}
                   onChange={e => setEditing({ ...editing, sap_data_permitted: e.target.checked })} />
            Permit SAP record data to be sent to this provider
          </label>
          {editing.sap_data_permitted && (
            <div className="form-warning">
              SAP records — including salaries, vendor bank details and invoice amounts —
              will be sent to this provider unredacted. Leave this off unless the provider
              is contractually approved for your enterprise data. The change is audited.
            </div>
          )}
          <div className="form-actions">
            <button className="btn-primary" onClick={save}>Save</button>
            <button className="btn-ghost" onClick={() => setEditing(null)}>Cancel</button>
          </div>
        </div>
      )}
    </>
  )
}
