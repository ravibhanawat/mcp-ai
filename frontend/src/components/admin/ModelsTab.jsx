import { useEffect, useState } from 'react'
import { apiJson } from '../../lib/api'

const PURPOSES = ['CHAT', 'REASONING', 'TOOL_CALLING', 'EMBEDDING', 'RERANKING',
                  'CLASSIFICATION', 'SUMMARIZATION']
const CAPABILITIES = ['chat', 'streaming', 'tool_calling', 'vision', 'embedding',
                      'json_mode', 'structured_output']
const PROFILES = [
  { id: 'registry_tool_json', label: 'Standard (tools generated from the registry)' },
  { id: 'trained_tool_json',  label: 'Fine-tuned (fixed trained tool-name list)' },
]

const BLANK = {
  provider_id: '', model_name: '', model_identifier: '', purpose: 'CHAT',
  context_window: 8192, max_tokens: 1024, temperature: 0.2,
  prompt_profile: 'registry_tool_json', capabilities: ['chat', 'streaming'],
}

export default function ModelsTab() {
  const [models, setModels] = useState([])
  const [providers, setProviders] = useState([])
  const [editing, setEditing] = useState(null)
  const [checks, setChecks] = useState(null)
  const [error, setError] = useState('')

  const load = async () => {
    try {
      setModels(await apiJson('/admin/ai/models'))
      setProviders(await apiJson('/admin/ai/providers'))
    } catch (e) { setError(e.message) }
  }
  useEffect(() => { load() }, [])

  const act = async (id, verb) => {
    setError(''); setChecks(null)
    try {
      await apiJson(`/admin/ai/models/${id}/${verb}`, { method: 'POST' })
      load()
    } catch (e) {
      // A failed activation returns the whole checklist; show it rather than
      // just "400 Bad Request", so the admin can see which check failed.
      if (e.body?.detail?.checks) setChecks(e.body.detail.checks)
      setError(e.message)
    }
  }

  const validate = async (id) => {
    setError('')
    try { setChecks((await apiJson(`/admin/ai/models/${id}/validate`, { method: 'POST' })).checks) }
    catch (e) { setError(e.message) }
  }

  const setDefault = async (model) => {
    const policy = await apiJson('/admin/ai/policy')
    const field = model.purpose === 'EMBEDDING' ? 'default_embedding_model_id'
                : model.purpose === 'RERANKING' ? 'default_reranker_model_id'
                : 'default_chat_model_id'
    await apiJson('/admin/ai/policy', {
      method: 'PUT', body: JSON.stringify({ ...policy, [field]: model.id }),
    })
    load()
  }

  const save = async () => {
    setError('')
    try {
      await apiJson(editing.id ? `/admin/ai/models/${editing.id}` : '/admin/ai/models', {
        method: editing.id ? 'PATCH' : 'POST', body: JSON.stringify(editing),
      })
      setEditing(null); load()
    } catch (e) { setError(e.message) }
  }

  const toggleCap = (cap) => setEditing(m => ({
    ...m,
    capabilities: m.capabilities.includes(cap)
      ? m.capabilities.filter(c => c !== cap)
      : [...m.capabilities, cap],
  }))

  const remove = async (id) => {
    if (!confirm('Delete this model? Routing rules and fallback entries that reference it are removed too.')) return
    setError(''); setChecks(null)
    try { await apiJson(`/admin/ai/models/${id}`, { method: 'DELETE' }); load() }
    catch (e) { setError(e.message) }
  }

  return (
    <>
      {error && <div className="form-error">{error}</div>}
      {checks && (
        <div className="form-panel">
          <strong>Validation</strong>
          {checks.map(c => (
            <div key={c.name} className={c.passed ? 'check-pass' : 'check-fail'}>
              {c.passed ? '✓' : '✕'} <code>{c.name}</code> — {c.detail}
            </div>
          ))}
        </div>
      )}

      <table className="dt-table">
        <thead>
          <tr>
            <th>Model</th><th>Provider</th><th>Purpose</th><th>Status</th>
            <th>Capabilities</th><th>Default</th><th>Last health check</th><th></th>
          </tr>
        </thead>
        <tbody>
          {models.map(m => (
            <tr key={m.id}>
              <td>{m.model_name}<div className="mono field-hint">{m.model_identifier}</div></td>
              <td>{m.provider_name}</td>
              <td>{m.purpose}</td>
              <td>{m.is_active ? 'Active' : 'Inactive'}</td>
              <td>{m.capabilities.map(c => <span key={c} className="pill">{c}</span>)}</td>
              <td>{m.is_default ? '✓' : ''}</td>
              <td>
                {m.health
                  ? `${m.health.status} · ${m.health.latency_ms ?? '—'} ms`
                  : 'Never checked'}
              </td>
              <td className="row-actions">
                <button className="btn-ghost" onClick={() => setEditing({ ...m })}>Edit</button>
                <button className="btn-ghost" onClick={() => act(m.id, 'test')}>Test</button>
                <button className="btn-ghost" onClick={() => validate(m.id)}>Validate</button>
                {m.is_active
                  ? <button className="btn-ghost" onClick={() => act(m.id, 'deactivate')}>Deactivate</button>
                  : <button className="btn-ghost" onClick={() => act(m.id, 'activate')}>Activate</button>}
                {!m.is_default && <button className="btn-ghost" onClick={() => setDefault(m)}>Set default</button>}
                <button className="btn-ghost danger" onClick={() => remove(m.id)}>Delete</button>
              </td>
            </tr>
          ))}
          {models.length === 0 && (
            <tr><td colSpan={8} className="empty">No models registered yet.</td></tr>
          )}
        </tbody>
      </table>

      <button className="btn-primary" onClick={() => setEditing({ ...BLANK })}>Add model</button>

      {editing && (
        <div className="form-panel">
          <label>Provider
            <select value={editing.provider_id}
                    onChange={e => setEditing({ ...editing, provider_id: e.target.value })}>
              <option value="">Select a provider…</option>
              {providers.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </label>
          <label>Display name
            <input value={editing.model_name}
                   onChange={e => setEditing({ ...editing, model_name: e.target.value })} />
          </label>
          <label>Model identifier
            <input value={editing.model_identifier}
                   onChange={e => setEditing({ ...editing, model_identifier: e.target.value })} />
            <span className="field-hint">
              Exactly as the provider names it. Use Test on the provider to see what it offers.
            </span>
          </label>
          <label>Purpose
            <select value={editing.purpose}
                    onChange={e => setEditing({ ...editing, purpose: e.target.value })}>
              {PURPOSES.map(p => <option key={p} value={p}>{p}</option>)}
            </select>
          </label>
          <label>Prompt profile
            <select value={editing.prompt_profile}
                    onChange={e => setEditing({ ...editing, prompt_profile: e.target.value })}>
              {PROFILES.map(p => <option key={p.id} value={p.id}>{p.label}</option>)}
            </select>
            <span className="field-hint">
              Fine-tuned models are trained against a fixed tool list and misbehave when
              given the generated one.
            </span>
          </label>
          <label>Context window
            <input type="number" value={editing.context_window}
                   onChange={e => setEditing({ ...editing, context_window: Number(e.target.value) })} />
          </label>
          <label>Max tokens
            <input type="number" value={editing.max_tokens}
                   onChange={e => setEditing({ ...editing, max_tokens: Number(e.target.value) })} />
          </label>
          <label>Temperature
            <input type="number" step="0.05" min="0" max="2" value={editing.temperature}
                   onChange={e => setEditing({ ...editing, temperature: Number(e.target.value) })} />
          </label>
          <fieldset className="caps">
            <legend>Capabilities</legend>
            <span className="field-hint">
              Declared here, then verified where a cheap probe exists. Nothing is assumed.
            </span>
            {CAPABILITIES.map(c => (
              <label key={c} className="checkbox">
                <input type="checkbox" checked={editing.capabilities.includes(c)}
                       onChange={() => toggleCap(c)} />{c}
              </label>
            ))}
          </fieldset>
          <div className="form-actions">
            <button className="btn-primary" onClick={save}>Save</button>
            <button className="btn-ghost" onClick={() => setEditing(null)}>Cancel</button>
          </div>
          <span className="field-hint">
            New models are saved inactive. Activate them once validation passes.
          </span>
        </div>
      )}
    </>
  )
}
