import { useEffect, useState } from 'react'
import { apiJson } from '../../lib/api'

const INTENTS = ['simple_chat', 'sap_tool_call', 'complex_reasoning', 'summarization', 'classification']
const PURPOSES = ['CHAT', 'REASONING', 'TOOL_CALLING', 'EMBEDDING', 'RERANKING',
                  'CLASSIFICATION', 'SUMMARIZATION']

export default function RoutingTab() {
  const [rules, setRules] = useState([])
  const [models, setModels] = useState([])
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    (async () => {
      try {
        setRules((await apiJson('/admin/ai/routing')).rules)
        setModels(await apiJson('/admin/ai/models'))
      } catch (e) { setError(e.message) }
    })()
  }, [])

  const update = (index, patch) =>
    setRules(rs => rs.map((r, i) => (i === index ? { ...r, ...patch } : r)))

  const save = async () => {
    setError(''); setSaved(false)
    try {
      const payload = rules.map(({ rule_type, match_key, model_id, priority }) =>
        ({ rule_type, match_key, model_id, priority: Number(priority) }))
      setRules((await apiJson('/admin/ai/routing', {
        method: 'PUT', body: JSON.stringify({ rules: payload }),
      })).rules)
      setSaved(true)
    } catch (e) { setError(e.message) }
  }

  return (
    <>
      {error && <div className="form-error">{error}</div>}
      <p className="field-hint">
        Rules are matched most specific first: an intent rule beats a purpose rule, which
        beats the tenant default. Lower priority numbers win.
      </p>
      <table className="dt-table">
        <thead><tr><th>Match on</th><th>Key</th><th>Model</th><th>Priority</th><th></th></tr></thead>
        <tbody>
          {rules.map((r, i) => (
            <tr key={i}>
              <td>
                <select value={r.rule_type} onChange={e => update(i, { rule_type: e.target.value })}>
                  <option value="purpose">Purpose</option>
                  <option value="intent">Intent</option>
                </select>
              </td>
              <td>
                {r.rule_type === 'purpose'
                  ? <select value={r.match_key} onChange={e => update(i, { match_key: e.target.value })}>
                      {PURPOSES.map(p => <option key={p} value={p}>{p}</option>)}
                    </select>
                  : <>
                      <input list="intent-keys" value={r.match_key}
                             onChange={e => update(i, { match_key: e.target.value })} />
                      <datalist id="intent-keys">
                        {INTENTS.map(k => <option key={k} value={k} />)}
                      </datalist>
                    </>}
              </td>
              <td>
                <select value={r.model_id} onChange={e => update(i, { model_id: e.target.value })}>
                  {models.map(m => (
                    <option key={m.id} value={m.id}>
                      {m.model_name}{m.is_active ? '' : ' (inactive)'}
                    </option>
                  ))}
                </select>
              </td>
              <td>
                <input type="number" value={r.priority}
                       onChange={e => update(i, { priority: e.target.value })} />
              </td>
              <td>
                <button className="btn-ghost danger"
                        onClick={() => setRules(rs => rs.filter((_, j) => j !== i))}>Remove</button>
              </td>
            </tr>
          ))}
          {rules.length === 0 && (
            <tr><td colSpan={5} className="empty">
              No rules. Every request uses the tenant default model for its purpose.
            </td></tr>
          )}
        </tbody>
      </table>
      <div className="form-actions">
        <button className="btn-ghost" onClick={() => setRules(rs => [...rs, {
          rule_type: 'purpose', match_key: 'CHAT', model_id: models[0]?.id || '', priority: 100,
        }])}>Add rule</button>
        <button className="btn-primary" onClick={save}>Save routing</button>
        {saved && <span className="check-pass">Saved.</span>}
      </div>
    </>
  )
}
