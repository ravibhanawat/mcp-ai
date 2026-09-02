import { useEffect, useState } from 'react'
import { apiJson } from '../../lib/api'

export default function FallbackTab() {
  const [chains, setChains] = useState({})
  const [models, setModels] = useState([])
  const [policy, setPolicy] = useState(null)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)

  const PURPOSES = ['CHAT', 'REASONING', 'TOOL_CALLING', 'EMBEDDING', 'RERANKING',
                    'CLASSIFICATION', 'SUMMARIZATION']

  useEffect(() => {
    (async () => {
      try {
        const fallback = await apiJson('/admin/ai/fallback')
        const modelsData = await apiJson('/admin/ai/models')
        const policyData = await apiJson('/admin/ai/policy')

        setModels(modelsData)
        setPolicy(policyData)

        // Group rules by purpose (match_key)
        const grouped = {}
        fallback.rules.forEach(r => {
          if (!grouped[r.match_key]) grouped[r.match_key] = []
          grouped[r.match_key].push(r)
        })
        // Sort each chain by priority
        Object.keys(grouped).forEach(key => {
          grouped[key].sort((a, b) => a.priority - b.priority)
        })
        setChains(grouped)
      } catch (e) { setError(e.message) }
    })()
  }, [])

  const moveUp = (purpose, idx) => {
    if (idx === 0) return
    setChains(c => ({
      ...c,
      [purpose]: c[purpose].map((m, i) =>
        i === idx - 1 ? c[purpose][idx] : i === idx ? c[purpose][idx - 1] : m
      )
    }))
  }

  const moveDown = (purpose, idx) => {
    if (idx === chains[purpose].length - 1) return
    setChains(c => ({
      ...c,
      [purpose]: c[purpose].map((m, i) =>
        i === idx + 1 ? c[purpose][idx] : i === idx ? c[purpose][idx + 1] : m
      )
    }))
  }

  const removeModel = (purpose, idx) => {
    setChains(c => ({
      ...c,
      [purpose]: c[purpose].filter((_, i) => i !== idx)
    }))
  }

  const addChain = (purpose) => {
    if (models.length === 0) return
    setChains(c => ({
      ...c,
      [purpose]: [{ model_id: models[0].id }]
    }))
  }

  const save = async () => {
    setError(''); setSaved(false)
    try {
      const chainPayload = Object.entries(chains)
        .filter(([_, models]) => models.length > 0)
        .map(([purpose, models]) => ({
          purpose,
          model_ids: models.map(m => m.model_id)
        }))

      await apiJson('/admin/ai/fallback', {
        method: 'PUT',
        body: JSON.stringify({ chains: chainPayload })
      })

      setSaved(true)
    } catch (e) { setError(e.message) }
  }

  const saveFallbackEnabled = async (enabled) => {
    if (!policy) return
    setError('')
    try {
      setPolicy(p => ({ ...p, fallback_enabled: enabled }))
      await apiJson('/admin/ai/policy', {
        method: 'PUT',
        body: JSON.stringify({ ...policy, fallback_enabled: enabled })
      })
    } catch (e) {
      setError(e.message)
      setPolicy(p => ({ ...p, fallback_enabled: !enabled }))
    }
  }

  const getModelName = (modelId) => {
    const m = models.find(mo => mo.id === modelId)
    return m ? m.model_name : modelId
  }

  return (
    <>
      {error && <div className="form-error">{error}</div>}

      <div className="form-panel">
        <label className="checkbox">
          <input type="checkbox" checked={policy?.fallback_enabled || false}
                 onChange={e => saveFallbackEnabled(e.target.checked)} />
          Enable failover chains
        </label>
        <span className="field-hint">
          When enabled, if a model is unreachable, times out, rate-limits, or rejects its credential,
          the system tries the next model in the chain for that purpose.
        </span>
      </div>

      <p className="field-hint">
        Failover happens only when a provider is unreachable, times out, rate-limits, or
        rejects its credential. A model that is missing a required capability is a
        configuration error and is reported rather than skipped. Models the tenant is not
        permitted to use are never tried.
      </p>

      {PURPOSES.map(purpose => (
        <div key={purpose} className="form-panel">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
            <strong>{purpose}</strong>
            {chains[purpose]?.length === 0 && (
              <button className="btn-ghost" onClick={() => addChain(purpose)}>Add chain</button>
            )}
          </div>

          {chains[purpose]?.length > 0 ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {chains[purpose].map((entry, idx) => (
                <div key={idx} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px', background: 'var(--bg-subtle)', borderRadius: '4px' }}>
                  <div style={{ flex: 1, fontSize: 13 }}>
                    {idx + 1}. {getModelName(entry.model_id)}
                  </div>
                  <div style={{ display: 'flex', gap: 4 }}>
                    <button className="btn-ghost" disabled={idx === 0}
                            onClick={() => moveUp(purpose, idx)}>Move up</button>
                    <button className="btn-ghost" disabled={idx === chains[purpose].length - 1}
                            onClick={() => moveDown(purpose, idx)}>Move down</button>
                    <button className="btn-ghost danger"
                            onClick={() => removeModel(purpose, idx)}>Remove</button>
                  </div>
                </div>
              ))}
              <button className="btn-ghost" onClick={() => {
                if (models.length === 0) return
                setChains(c => ({
                  ...c,
                  [purpose]: [...(c[purpose] || []), { model_id: models[0].id }]
                }))
              }}>Add model</button>
            </div>
          ) : (
            <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>No fallback chain configured.</div>
          )}
        </div>
      ))}

      <div className="form-actions">
        <button className="btn-primary" onClick={save}>Save fallback chains</button>
        {saved && <span className="check-pass">Saved.</span>}
      </div>
    </>
  )
}
