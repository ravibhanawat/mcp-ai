/**
 * ReceiptWidget — Alembic Parivartan Project
 * 3-step wizard: Lookup → Entry → Park/Post
 * Maps to ZFI_RECEIPT_PARK and ZFI_RECEIPT_POST T-codes
 */
import { useState } from 'react'

const PAYMENT_MODES = [
  'Cheque',
  'Demand Draft',
  'Direct Remittance',
  'TDS',
  'Debit/Credit Card',
  'Cash',
  'Credit Note Basic Excess',
  'Credit Note TDS Excess',
  'On Account',
  'Journal Voucher',
]

const API = '/api'

async function apiFetch(path, options = {}) {
  const token = localStorage.getItem('sap_agent_token')
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) }
  if (token) headers['Authorization'] = `Bearer ${token}`
  return fetch(`${API}${path}`, { ...options, headers })
}

function fmt(n) {
  if (n == null) return '—'
  return '₹' + Number(n).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function StatusBadge({ status }) {
  const colors = {
    COLLECTED: '#16a34a', PARTIAL: '#d97706', PENDING: '#64748b',
    PARKED: '#7c3aed', POSTED: '#0070d2', REVERSED: '#dc2626',
    VALID: '#16a34a', MISSING_IRN: '#dc2626', B2C_EXEMPT: '#64748b',
  }
  return (
    <span style={{
      background: colors[status] || '#64748b',
      color: '#fff', borderRadius: 4,
      padding: '1px 8px', fontSize: 11, fontWeight: 600,
    }}>{status}</span>
  )
}

function Step1Lookup({ onResult }) {
  const [customerId, setCustomerId] = useState('ALEC001')
  const [unitNumber, setUnitNumber] = useState('T1-304')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  async function handleLookup(e) {
    e.preventDefault()
    setLoading(true); setError(null)
    try {
      const res = await apiFetch('/chat', {
        method: 'POST',
        body: JSON.stringify({
          message: `get outstanding for customer ${customerId} unit ${unitNumber}`,
          tool_override: 'get_customer_unit_outstanding',
          tool_params: { customer_id: customerId, unit_number: unitNumber },
        }),
      })
      const data = await res.json()
      const toolResult = data.tool_result || data
      if (toolResult.status === 'ERROR') {
        setError(toolResult.message)
      } else {
        onResult(toolResult)
      }
    } catch (err) {
      setError('Connection error. Check API server.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ padding: '16px 0' }}>
      <div style={{ fontSize: 13, color: '#64748b', marginBottom: 12 }}>
        Enter customer and unit to fetch outstanding milestone dues.
      </div>
      <form onSubmit={handleLookup} style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <input
          value={customerId}
          onChange={e => setCustomerId(e.target.value.toUpperCase())}
          placeholder="Customer ID (e.g. ALEC001)"
          style={inputStyle}
        />
        <input
          value={unitNumber}
          onChange={e => setUnitNumber(e.target.value.toUpperCase())}
          placeholder="Unit No. (e.g. T1-304)"
          style={inputStyle}
        />
        <button type="submit" disabled={loading} style={btnStyle('#0070d2')}>
          {loading ? 'Loading…' : 'Fetch Outstanding'}
        </button>
      </form>
      {error && <div style={errorStyle}>{error}</div>}
    </div>
  )
}

function Step1Results({ data, onProceed }) {
  if (!data) return null
  const items = data.outstanding_items || []
  return (
    <div>
      <div style={{ marginBottom: 12 }}>
        <strong>{data.customer_name}</strong>
        <span style={{ color: '#64748b', marginLeft: 8 }}>
          {data.project?.replace('_', ' ')} | {data.unit_number} | {data.tower} Floor {data.floor}
        </span>
      </div>

      <table style={tableStyle}>
        <thead>
          <tr style={{ background: '#f1f5f9' }}>
            {['Milestone','Billing Doc','Basic Outstanding','CGST','SGST','Net Outstanding','Status'].map(h => (
              <th key={h} style={thStyle}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {items.map(m => (
            <tr key={m.milestone_code} style={{ borderBottom: '1px solid #e2e8f0' }}>
              <td style={tdStyle}><strong>{m.milestone_code}</strong> — {m.description}</td>
              <td style={tdStyle}>{m.billing_doc_no || '—'}</td>
              <td style={{ ...tdStyle, textAlign: 'right' }}>{fmt(m.basic_outstanding)}</td>
              <td style={{ ...tdStyle, textAlign: 'right' }}>{fmt(m.cgst_outstanding)}</td>
              <td style={{ ...tdStyle, textAlign: 'right' }}>{fmt(m.sgst_outstanding)}</td>
              <td style={{ ...tdStyle, textAlign: 'right', fontWeight: 600 }}>{fmt(m.net_outstanding)}</td>
              <td style={tdStyle}><StatusBadge status={m.status} /></td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr style={{ background: '#f8fafc', fontWeight: 700 }}>
            <td colSpan={2} style={tdStyle}>Total Outstanding</td>
            <td style={{ ...tdStyle, textAlign: 'right' }}>{fmt(data.total_basic_outstanding)}</td>
            <td style={{ ...tdStyle, textAlign: 'right' }}>{fmt(data.total_cgst_outstanding)}</td>
            <td style={{ ...tdStyle, textAlign: 'right' }}>{fmt(data.total_sgst_outstanding)}</td>
            <td style={{ ...tdStyle, textAlign: 'right' }}>{fmt(data.total_outstanding)}</td>
            <td style={tdStyle} />
          </tr>
        </tfoot>
      </table>

      {items.length === 0 && (
        <div style={{ color: '#16a34a', marginTop: 8 }}>All milestones fully collected.</div>
      )}

      {items.length > 0 && (
        <button onClick={onProceed} style={{ ...btnStyle('#B45309'), marginTop: 12 }}>
          Proceed to Receipt Entry →
        </button>
      )}
    </div>
  )
}

function Step2Entry({ outstandingData, onParked }) {
  const [paymentMode, setPaymentMode] = useState('Cheque')
  const [amount, setAmount]           = useState('')
  const [instrumentRef, setRef]       = useState('')
  const [instrumentDate, setDate]     = useState(new Date().toISOString().slice(0, 10))
  const [bankName, setBank]           = useState('')
  const [preview, setPreview]         = useState(null)
  const [loading, setLoading]         = useState(false)
  const [parking, setParking]         = useState(false)
  const [error, setError]             = useState(null)

  const customerId = outstandingData.customer_id
  const unitNumber = outstandingData.unit_number

  async function handlePreview() {
    if (!amount || isNaN(amount)) { setError('Enter a valid amount'); return }
    setLoading(true); setError(null)
    try {
      const res = await apiFetch('/chat', {
        method: 'POST',
        body: JSON.stringify({
          message: `calculate allocation`,
          tool_override: 'calculate_receipt_allocation',
          tool_params: {
            customer_id: customerId, unit_number: unitNumber,
            payment_mode: paymentMode, amount: parseFloat(amount),
          },
        }),
      })
      const data = await res.json()
      const result = data.tool_result || data
      if (result.status === 'ERROR') setError(result.message)
      else setPreview(result)
    } catch { setError('Connection error.') }
    finally { setLoading(false) }
  }

  async function handlePark() {
    if (!instrumentRef || !instrumentDate) { setError('Fill instrument reference and date'); return }
    setParking(true); setError(null)
    try {
      const res = await apiFetch('/chat', {
        method: 'POST',
        body: JSON.stringify({
          message: `park receipt`,
          tool_override: 'park_customer_receipt',
          tool_params: {
            customer_id: customerId, unit_number: unitNumber,
            payment_mode: paymentMode, amount: parseFloat(amount),
            instrument_ref: instrumentRef, instrument_date: instrumentDate,
            bank_name: bankName,
          },
        }),
      })
      const data = await res.json()
      const result = data.tool_result || data
      if (result.status === 'ERROR') setError(result.message)
      else onParked(result)
    } catch { setError('Connection error.') }
    finally { setParking(false) }
  }

  return (
    <div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 16 }}>
        <div>
          <label style={labelStyle}>Payment Mode</label>
          <select value={paymentMode} onChange={e => { setPaymentMode(e.target.value); setPreview(null) }} style={inputStyle}>
            {PAYMENT_MODES.map(m => <option key={m}>{m}</option>)}
          </select>
        </div>
        <div>
          <label style={labelStyle}>Amount (INR)</label>
          <input
            type="number" value={amount}
            onChange={e => { setAmount(e.target.value); setPreview(null) }}
            placeholder="e.g. 500000"
            style={inputStyle}
          />
        </div>
        <div>
          <label style={labelStyle}>Instrument Ref (Cheque/DD/UTR)</label>
          <input value={instrumentRef} onChange={e => setRef(e.target.value)} placeholder="e.g. CH123456" style={inputStyle} />
        </div>
        <div>
          <label style={labelStyle}>Instrument Date</label>
          <input type="date" value={instrumentDate} onChange={e => setDate(e.target.value)} style={inputStyle} />
        </div>
        <div>
          <label style={labelStyle}>Bank Name</label>
          <input value={bankName} onChange={e => setBank(e.target.value)} placeholder="e.g. HDFC Bank" style={inputStyle} />
        </div>
      </div>

      <button onClick={handlePreview} disabled={loading} style={btnStyle('#0070d2')}>
        {loading ? 'Calculating…' : 'Preview FIFO Allocation'}
      </button>

      {error && <div style={errorStyle}>{error}</div>}

      {preview && (
        <div style={{ marginTop: 16 }}>
          <div style={{ fontWeight: 600, marginBottom: 8 }}>Allocation Preview</div>
          <table style={tableStyle}>
            <thead>
              <tr style={{ background: '#f1f5f9' }}>
                {['Milestone','Basic Applied','CGST','SGST','TDS'].map(h => (
                  <th key={h} style={thStyle}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {preview.allocation.map((a, i) => (
                <tr key={i} style={{ borderBottom: '1px solid #e2e8f0' }}>
                  <td style={tdStyle}><strong>{a.milestone_code}</strong> — {a.description}</td>
                  <td style={{ ...tdStyle, textAlign: 'right' }}>{fmt(a.basic_applied)}</td>
                  <td style={{ ...tdStyle, textAlign: 'right' }}>{fmt(a.cgst_applied)}</td>
                  <td style={{ ...tdStyle, textAlign: 'right' }}>{fmt(a.sgst_applied)}</td>
                  <td style={{ ...tdStyle, textAlign: 'right' }}>{fmt(a.tds_applied)}</td>
                </tr>
              ))}
            </tbody>
          </table>

          {(preview.excess_basic > 0 || preview.excess_tds > 0) && (
            <div style={{ background: '#fef3c7', border: '1px solid #d97706', borderRadius: 6, padding: '8px 12px', marginTop: 8 }}>
              ⚠ Excess amounts will be carried forward:
              {preview.excess_basic > 0 && <> Basic Excess: <strong>{fmt(preview.excess_basic)}</strong></>}
              {preview.excess_tds > 0   && <> TDS Excess: <strong>{fmt(preview.excess_tds)}</strong></>}
            </div>
          )}

          <button onClick={handlePark} disabled={parking} style={{ ...btnStyle('#B45309'), marginTop: 12 }}>
            {parking ? 'Parking…' : 'Park Receipt (ZFI_RECEIPT_PARK)'}
          </button>
        </div>
      )}
    </div>
  )
}

function Step3PostReceipt({ parkedData, onPosted }) {
  const [posting, setPosting] = useState(false)
  const [posted, setPosted]   = useState(null)
  const [error, setError]     = useState(null)

  async function handlePost() {
    setPosting(true); setError(null)
    try {
      const res = await apiFetch('/chat', {
        method: 'POST',
        body: JSON.stringify({
          message: `post receipt`,
          tool_override: 'post_customer_receipt',
          tool_params: { park_reference: parkedData.park_reference },
        }),
      })
      const data = await res.json()
      const result = data.tool_result || data
      if (result.status === 'ERROR') setError(result.message)
      else { setPosted(result); onPosted && onPosted(result) }
    } catch { setError('Connection error.') }
    finally { setPosting(false) }
  }

  return (
    <div>
      <div style={{
        background: '#f0fdf4', border: '1px solid #16a34a',
        borderRadius: 8, padding: '14px 18px', marginBottom: 16,
      }}>
        <div style={{ fontWeight: 700, color: '#16a34a', marginBottom: 6 }}>
          Receipt Parked Successfully
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6, fontSize: 13 }}>
          <div><span style={{ color: '#64748b' }}>Park Reference:</span> <strong>{parkedData.park_reference}</strong></div>
          <div><span style={{ color: '#64748b' }}>Payment Mode:</span> {parkedData.payment_mode}</div>
          <div><span style={{ color: '#64748b' }}>Amount:</span> <strong>{fmt(parkedData.amount)}</strong></div>
          <div><span style={{ color: '#64748b' }}>Customer:</span> {parkedData.customer_name}</div>
        </div>

        {parkedData.allocation && parkedData.allocation.length > 0 && (
          <table style={{ ...tableStyle, marginTop: 12 }}>
            <thead>
              <tr style={{ background: '#dcfce7' }}>
                {['Milestone','Basic','CGST','SGST','TDS'].map(h => (
                  <th key={h} style={thStyle}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {parkedData.allocation.map((a, i) => (
                <tr key={i} style={{ borderBottom: '1px solid #e2e8f0' }}>
                  <td style={tdStyle}>{a.milestone_code} — {a.description}</td>
                  <td style={{ ...tdStyle, textAlign: 'right' }}>{fmt(a.basic_applied)}</td>
                  <td style={{ ...tdStyle, textAlign: 'right' }}>{fmt(a.cgst_applied)}</td>
                  <td style={{ ...tdStyle, textAlign: 'right' }}>{fmt(a.sgst_applied)}</td>
                  <td style={{ ...tdStyle, textAlign: 'right' }}>{fmt(a.tds_applied)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {!posted && (
        <>
          <button onClick={handlePost} disabled={posting} style={btnStyle('#0070d2')}>
            {posting ? 'Posting to FI…' : 'Post Receipt to FI (ZFI_RECEIPT_POST)'}
          </button>
          {error && <div style={errorStyle}>{error}</div>}
        </>
      )}

      {posted && (
        <div style={{
          background: '#eff6ff', border: '1px solid #0070d2',
          borderRadius: 8, padding: '14px 18px',
        }}>
          <div style={{ fontWeight: 700, color: '#0070d2', marginBottom: 6 }}>
            Posted to FI Successfully
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6, fontSize: 13 }}>
            <div><span style={{ color: '#64748b' }}>FI Document:</span> <strong>{posted.fi_doc_no}</strong></div>
            <div><span style={{ color: '#64748b' }}>Amount Posted:</span> <strong>{fmt(posted.posted_amount)}</strong></div>
            <div><span style={{ color: '#64748b' }}>Status:</span> <StatusBadge status="POSTED" /></div>
          </div>
        </div>
      )}
    </div>
  )
}

export default function ReceiptWidget({ initialData, onClose }) {
  const [step, setStep]                   = useState(initialData ? 2 : 1)
  const [outstandingData, setOutstanding] = useState(initialData || null)
  const [parkedData, setParked]           = useState(null)

  const steps = ['1. Lookup Outstanding', '2. Enter Receipt', '3. Park & Post']

  return (
    <div style={{
      background: '#fff', border: '1px solid #e2e8f0', borderRadius: 10,
      padding: '20px 24px', margin: '12px 0', boxShadow: '0 2px 8px rgba(0,0,0,0.07)',
    }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div>
          <div style={{ fontWeight: 700, fontSize: 15, color: '#B45309' }}>
            Customer Receipt Entry
          </div>
          <div style={{ fontSize: 12, color: '#64748b' }}>
            ZFI_RECEIPT_PARK / ZFI_RECEIPT_POST — Alembic Parivartan Project
          </div>
        </div>
        {onClose && (
          <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#64748b', fontSize: 18 }}>×</button>
        )}
      </div>

      {/* Step indicator */}
      <div style={{ display: 'flex', gap: 0, marginBottom: 20 }}>
        {steps.map((s, i) => {
          const idx = i + 1
          const active = idx === step
          const done   = idx < step
          return (
            <div key={s} style={{ flex: 1, display: 'flex', alignItems: 'center' }}>
              <div style={{
                background: done ? '#16a34a' : active ? '#B45309' : '#e2e8f0',
                color: (done || active) ? '#fff' : '#64748b',
                borderRadius: 20, padding: '4px 14px', fontSize: 12, fontWeight: 600, whiteSpace: 'nowrap',
              }}>{done ? '✓ ' : ''}{s}</div>
              {i < steps.length - 1 && <div style={{ flex: 1, height: 2, background: done ? '#16a34a' : '#e2e8f0' }} />}
            </div>
          )
        })}
      </div>

      {/* Step content */}
      {step === 1 && (
        <>
          <Step1Lookup onResult={data => { setOutstanding(data); }} />
          {outstandingData && (
            <Step1Results
              data={outstandingData}
              onProceed={() => setStep(2)}
            />
          )}
        </>
      )}

      {step === 2 && outstandingData && (
        <>
          <div style={{ marginBottom: 12 }}>
            <strong>{outstandingData.customer_name}</strong>
            <span style={{ color: '#64748b', marginLeft: 8 }}>
              {outstandingData.unit_number} | Total Outstanding: <strong>{fmt(outstandingData.total_outstanding)}</strong>
            </span>
          </div>
          <Step2Entry
            outstandingData={outstandingData}
            onParked={data => { setParked(data); setStep(3) }}
          />
        </>
      )}

      {step === 3 && parkedData && (
        <Step3PostReceipt parkedData={parkedData} />
      )}

      {/* Back/Reset */}
      <div style={{ marginTop: 16, borderTop: '1px solid #f1f5f9', paddingTop: 12 }}>
        {step > 1 && (
          <button
            onClick={() => { if (step === 2) { setStep(1); setOutstanding(null) } else setStep(2) }}
            style={{ ...btnStyle('#64748b'), marginRight: 8 }}
          >
            ← Back
          </button>
        )}
        <button onClick={() => { setStep(1); setOutstanding(null); setParked(null) }} style={btnStyle('#94a3b8')}>
          Reset
        </button>
      </div>
    </div>
  )
}

// ── Styles ───────────────────────────────────────────────────────────────────
const inputStyle = {
  border: '1px solid #e2e8f0', borderRadius: 6, padding: '7px 10px',
  fontSize: 13, width: '100%', background: '#f8fafc',
  outline: 'none', boxSizing: 'border-box',
}
const labelStyle = { fontSize: 12, color: '#64748b', display: 'block', marginBottom: 4 }
const btnStyle = color => ({
  background: color, color: '#fff', border: 'none', borderRadius: 6,
  padding: '7px 16px', fontSize: 13, cursor: 'pointer', fontWeight: 600,
})
const errorStyle = {
  background: '#fef2f2', border: '1px solid #fca5a5', color: '#b91c1c',
  borderRadius: 6, padding: '8px 12px', fontSize: 13, marginTop: 8,
}
const tableStyle = {
  width: '100%', borderCollapse: 'collapse', fontSize: 12,
  border: '1px solid #e2e8f0', borderRadius: 6, overflow: 'hidden',
}
const thStyle = { padding: '6px 10px', textAlign: 'left', fontWeight: 600, fontSize: 11, color: '#475569' }
const tdStyle  = { padding: '6px 10px', color: '#334155' }
