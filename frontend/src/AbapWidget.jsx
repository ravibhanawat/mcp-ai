/**
 * SAP AI Agent — ABAP Code Review Widget
 *
 * Renders inline inside chat when the backend returns an abap_check payload.
 * Shows: quality score badge, errors/warnings/suggestions, good practices,
 * and the code itself with problem lines highlighted.
 *
 * Also exports: <AbapCodePad> — the input panel for the ABAP module
 * that lets developers paste code and hit "Check" without typing a query.
 */

import { useState } from 'react'

// ─── Severity config ──────────────────────────────────────────────────────────

const SEV = {
  ERROR:   { color: '#dc2626', bg: 'rgba(220,38,38,0.10)',   icon: '✕', label: 'Error'      },
  WARNING: { color: '#d97706', bg: 'rgba(217,119,6,0.12)',   icon: '⚠', label: 'Warning'    },
  INFO:    { color: '#0891b2', bg: 'rgba(8,145,178,0.10)',   icon: 'ℹ', label: 'Info'       },
  SUGGEST: { color: '#7c3aed', bg: 'rgba(124,58,237,0.10)',  icon: '✦', label: 'Suggestion' },
  GOOD:    { color: '#16a34a', bg: 'rgba(22,163,74,0.10)',   icon: '✓', label: 'Good'       },
}

// ─── Quality score ring ───────────────────────────────────────────────────────

function ScoreRing({ score, rating }) {
  const r = 28
  const circ = 2 * Math.PI * r
  const filled = circ * (score / 100)
  const color = score >= 75 ? '#16a34a' : score >= 50 ? '#d97706' : '#dc2626'
  const ratingColor = { EXCELLENT: '#16a34a', GOOD: '#16a34a', NEEDS_REVIEW: '#d97706', POOR: '#dc2626' }[rating] || '#d97706'

  return (
    <div className="abap-score-ring">
      <svg width="76" height="76" viewBox="0 0 76 76">
        <circle cx="38" cy="38" r={r} fill="none" stroke="var(--bg-subtle)" strokeWidth="6" />
        <circle
          cx="38" cy="38" r={r}
          fill="none"
          stroke={color}
          strokeWidth="6"
          strokeDasharray={`${filled} ${circ}`}
          strokeLinecap="round"
          transform="rotate(-90 38 38)"
          style={{ transition: 'stroke-dasharray 0.6s ease' }}
        />
        <text x="38" y="34" textAnchor="middle" fontSize="14" fontWeight="800" fill={color}>{score}</text>
        <text x="38" y="46" textAnchor="middle" fontSize="8"  fill="var(--text-secondary)">/100</text>
      </svg>
      <div className="abap-score-label" style={{ color: ratingColor }}>{rating}</div>
    </div>
  )
}

// ─── Issue row ────────────────────────────────────────────────────────────────

function IssueRow({ item, type }) {
  const cfg = SEV[type] || SEV.INFO
  return (
    <div className="abap-issue-row" style={{ borderLeft: `3px solid ${cfg.color}`, background: cfg.bg }}>
      <span className="abap-issue-icon" style={{ color: cfg.color }}>{cfg.icon}</span>
      <div className="abap-issue-body">
        <div className="abap-issue-top">
          <span className="abap-issue-code" style={{ color: cfg.color }}>{item.code}</span>
          <span className="abap-issue-msg">{item.message}</span>
          {item.line && <span className="abap-issue-line">Line {item.line}</span>}
        </div>
        {item.hint && <div className="abap-issue-hint">💡 {item.hint}</div>}
      </div>
    </div>
  )
}

// ─── Code viewer with line highlights ────────────────────────────────────────

function CodeViewer({ code, issues = [], suggestions = [] }) {
  const [copied, setCopied] = useState(false)

  const problemLines = new Set([
    ...issues.map(i => i.line),
    ...suggestions.map(s => s.line),
  ])

  const issueMap = {}
  for (const iss of issues) {
    if (!issueMap[iss.line]) issueMap[iss.line] = []
    issueMap[iss.line].push({ ...iss, type: iss.severity || 'ERROR' })
  }
  for (const sug of suggestions) {
    if (!issueMap[sug.line]) issueMap[sug.line] = []
    issueMap[sug.line].push({ ...sug, type: 'SUGGEST' })
  }

  const doCopy = () => {
    navigator.clipboard.writeText(code)
    setCopied(true); setTimeout(() => setCopied(false), 1800)
  }

  return (
    <div className="abap-code-viewer">
      <div className="abap-code-head">
        <span className="abap-code-lang">ABAP</span>
        <button className={`abap-copy-btn ${copied ? 'copied' : ''}`} onClick={doCopy}>
          {copied ? 'Copied!' : 'Copy'}
        </button>
      </div>
      <div className="abap-code-scroll">
        {code.split('\n').map((line, idx) => {
          const lineNo = idx + 1
          const hasIssue = problemLines.has(lineNo)
          const lineProblems = issueMap[lineNo] || []
          const worstSev = lineProblems.find(p => p.type === 'ERROR') ? 'ERROR'
                         : lineProblems.find(p => p.type === 'WARNING') ? 'WARNING'
                         : lineProblems.length ? 'SUGGEST' : null
          const bg = worstSev ? SEV[worstSev]?.bg : 'transparent'

          return (
            <div key={lineNo} className={`abap-line ${hasIssue ? 'abap-line--problem' : ''}`}
                 style={{ background: bg }}>
              <span className="abap-line-no">{lineNo}</span>
              {worstSev && (
                <span className="abap-line-marker" style={{ color: SEV[worstSev].color }}
                      title={lineProblems.map(p => p.message).join(' | ')}>
                  {SEV[worstSev].icon}
                </span>
              )}
              <span className="abap-line-code">{line || ' '}</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ─── Main ABAP Review Widget ──────────────────────────────────────────────────

/**
 * @param {{ abap_check: object }} props
 */
export function AbapReviewWidget({ abap_check }) {
  const [showCode, setShowCode] = useState(false)
  const [tab, setTab] = useState('issues')   // 'issues' | 'suggestions' | 'good'

  if (!abap_check) return null

  const {
    quality_score, rating, lines_analyzed,
    error_count, warning_count, suggestion_count,
    issues = [], suggestions = [], info = [], good_practices = [],
    code,
  } = abap_check

  const tabs = [
    { id: 'issues',      label: `Errors & Warnings (${(error_count || 0) + (warning_count || 0)})` },
    { id: 'suggestions', label: `Suggestions (${suggestion_count || 0})` },
    { id: 'good',        label: `Good Practices (${good_practices.length})` },
  ]

  return (
    <div className="abap-widget">
      {/* ── Header ── */}
      <div className="abap-widget-header">
        <div className="abap-widget-title">
          <span className="abap-widget-icon">⌨</span>
          ABAP Code Review
        </div>
        <span className="abap-lines-badge">{lines_analyzed} lines</span>
      </div>

      {/* ── Score + summary ── */}
      <div className="abap-summary">
        <ScoreRing score={quality_score} rating={rating} />
        <div className="abap-summary-stats">
          <div className="abap-stat abap-stat--error">
            <span className="abap-stat-num">{error_count}</span>
            <span className="abap-stat-lbl">Errors</span>
          </div>
          <div className="abap-stat abap-stat--warning">
            <span className="abap-stat-num">{warning_count}</span>
            <span className="abap-stat-lbl">Warnings</span>
          </div>
          <div className="abap-stat abap-stat--suggest">
            <span className="abap-stat-num">{suggestion_count}</span>
            <span className="abap-stat-lbl">Suggestions</span>
          </div>
          <div className="abap-stat abap-stat--good">
            <span className="abap-stat-num">{good_practices.length}</span>
            <span className="abap-stat-lbl">Good</span>
          </div>
        </div>
      </div>

      {/* ── Tabs ── */}
      <div className="abap-tabs">
        {tabs.map(t => (
          <button
            key={t.id}
            className={`abap-tab ${tab === t.id ? 'active' : ''}`}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* ── Tab content ── */}
      <div className="abap-tab-body">
        {tab === 'issues' && (
          <div className="abap-issue-list">
            {issues.length === 0 && <div className="abap-empty">No errors or warnings found.</div>}
            {issues.map((iss, i) => (
              <IssueRow key={i} item={iss} type={iss.severity || 'ERROR'} />
            ))}
            {info.map((item, i) => (
              <IssueRow key={`info-${i}`} item={item} type="INFO" />
            ))}
          </div>
        )}

        {tab === 'suggestions' && (
          <div className="abap-issue-list">
            {suggestions.length === 0 && <div className="abap-empty">No suggestions — looking clean!</div>}
            {suggestions.map((s, i) => (
              <IssueRow key={i} item={s} type="SUGGEST" />
            ))}
          </div>
        )}

        {tab === 'good' && (
          <div className="abap-issue-list">
            {good_practices.length === 0 && (
              <div className="abap-empty">No good-practice patterns detected yet.</div>
            )}
            {good_practices.map((g, i) => (
              <div key={i} className="abap-issue-row"
                   style={{ borderLeft: `3px solid ${SEV.GOOD.color}`, background: SEV.GOOD.bg }}>
                <span className="abap-issue-icon" style={{ color: SEV.GOOD.color }}>{SEV.GOOD.icon}</span>
                <div className="abap-issue-body">
                  <div className="abap-issue-msg">{g}</div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ── Code viewer toggle ── */}
      {code && (
        <div className="abap-code-section">
          <button className="abap-toggle-code" onClick={() => setShowCode(v => !v)}>
            {showCode ? '▲ Hide Code' : '▼ View Annotated Code'}
          </button>
          {showCode && <CodeViewer code={code} issues={issues} suggestions={suggestions} />}
        </div>
      )}
    </div>
  )
}

// ─── ABAP Generated Code Widget ──────────────────────────────────────────────

/**
 * Shown inline in chat when the backend returns an abap_code payload.
 * @param {{ abap_code: object }} props
 */
export function AbapCodeWidget({ abap_code }) {
  const [copied, setCopied] = useState(false)
  if (!abap_code) return null

  const { code, code_type, transport_id, tables_used, tcode, instructions = [] } = abap_code

  const doCopy = () => {
    navigator.clipboard.writeText(code)
    setCopied(true)
    setTimeout(() => setCopied(false), 1800)
  }

  return (
    <div className="abap-widget">
      <div className="abap-widget-header">
        <div className="abap-widget-title">
          <span className="abap-widget-icon">⌨</span>
          Generated ABAP — {code_type}
        </div>
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          {tcode && <span className="abap-lines-badge">{tcode}</span>}
          {transport_id && <span className="abap-lines-badge">{transport_id}</span>}
        </div>
      </div>

      {tables_used && tables_used.length > 0 && (
        <div style={{ padding: '6px 14px', fontSize: '12px', color: 'var(--text-secondary)' }}>
          Tables: {tables_used.join(', ')}
        </div>
      )}

      <div className="abap-code-viewer">
        <div className="abap-code-head">
          <span className="abap-code-lang">ABAP</span>
          <button className={`abap-copy-btn ${copied ? 'copied' : ''}`} onClick={doCopy}>
            {copied ? 'Copied!' : 'Copy'}
          </button>
        </div>
        <div className="abap-code-scroll">
          {(code || '').split('\n').map((line, idx) => (
            <div key={idx} className="abap-line">
              <span className="abap-line-no">{idx + 1}</span>
              <span className="abap-line-code">{line || ' '}</span>
            </div>
          ))}
        </div>
      </div>

      {instructions.length > 0 && (
        <div style={{ padding: '10px 14px', borderTop: '1px solid var(--border)', fontSize: '13px' }}>
          <div style={{ fontWeight: 600, marginBottom: '6px', color: 'var(--text-primary)' }}>How to use:</div>
          {instructions.map((step, i) => (
            <div key={i} style={{ color: 'var(--text-secondary)', marginBottom: '3px' }}>{step}</div>
          ))}
        </div>
      )}
    </div>
  )
}

// ─── Code Pad (input panel for ABAP module) ───────────────────────────────────

/**
 * Shown in the chat area when the ABAP module is selected.
 * Lets the developer paste code directly and click "Check" to send it.
 *
 * @param {{ onSubmit: (msg: string) => void, disabled: boolean }} props
 */
export function AbapCodePad({ onSubmit, disabled }) {
  const [code, setCode] = useState('')
  const [mode, setMode] = useState('check')   // 'check' | 'generate'

  const TEMPLATES = {
    select:  `REPORT ZTEST_SELECT.\n\nDATA: lt_vbak TYPE TABLE OF vbak,\n      ls_vbak TYPE vbak.\n\nSELECT vbeln waerk auart FROM vbak\n  INTO TABLE lt_vbak\n  WHERE waerk = 'INR'.\n\nIF sy-subrc = 0.\n  LOOP AT lt_vbak INTO ls_vbak.\n    WRITE: / ls_vbak-vbeln, ls_vbak-waerk.\n  ENDLOOP.\nENDIF.`,
    bapi:    `REPORT ZTEST_BAPI.\n\nDATA: ls_return TYPE bapiret2.\n\nCALL FUNCTION 'BAPI_TRANSACTION_COMMIT'\n  EXPORTING\n    wait = 'X'\n  IMPORTING\n    return = ls_return.\n\nIF ls_return-type = 'E'.\n  MESSAGE ls_return-message TYPE 'E'.\nENDIF.`,
    class:   `CLASS zcl_example DEFINITION\n  PUBLIC\n  FINAL\n  CREATE PUBLIC.\n\n  PUBLIC SECTION.\n    METHODS: constructor,\n             get_data RETURNING VALUE(rv_result) TYPE string.\n\n  PRIVATE SECTION.\n    DATA: mv_data TYPE string.\n\nENDCLASS.\n\nCLASS zcl_example IMPLEMENTATION.\n  METHOD constructor.\n    mv_data = 'Hello SAP'.\n  ENDMETHOD.\n\n  METHOD get_data.\n    rv_result = mv_data.\n  ENDMETHOD.\nENDCLASS.`,
  }

  const handleCheck = () => {
    if (!code.trim()) return
    onSubmit('```abap\n' + code.trim() + '\n```')
    setCode('')
  }

  const handleGenerate = () => {
    if (!code.trim()) return
    onSubmit('Generate ABAP code for: ' + code.trim())
    setCode('')
  }

  const loadTemplate = (key) => setCode(TEMPLATES[key] || '')

  return (
    <div className="abap-pad">
      <div className="abap-pad-header">
        <div className="abap-pad-tabs">
          <button className={`abap-pad-tab ${mode === 'check' ? 'active' : ''}`}
                  onClick={() => setMode('check')}>
            ⌨ Check Code
          </button>
          <button className={`abap-pad-tab ${mode === 'generate' ? 'active' : ''}`}
                  onClick={() => setMode('generate')}>
            ✦ Generate Code
          </button>
        </div>
        {mode === 'check' && (
          <div className="abap-template-btns">
            <span className="abap-template-label">Templates:</span>
            <button className="abap-tpl-btn" onClick={() => loadTemplate('select')}>SELECT</button>
            <button className="abap-tpl-btn" onClick={() => loadTemplate('bapi')}>BAPI CALL</button>
            <button className="abap-tpl-btn" onClick={() => loadTemplate('class')}>Class</button>
          </div>
        )}
      </div>

      <textarea
        className="abap-pad-editor"
        value={code}
        onChange={e => setCode(e.target.value)}
        placeholder={mode === 'check'
          ? 'Paste your ABAP code here… (or load a template above)'
          : 'Describe what you need — e.g. "read all open sales orders for customer C001"'}
        spellCheck={false}
        disabled={disabled}
        rows={10}
      />

      <div className="abap-pad-footer">
        <span className="abap-line-count">
          {code.split('\n').length} line{code.split('\n').length !== 1 ? 's' : ''}
        </span>
        <div className="abap-pad-actions">
          {code.trim() && (
            <button className="abap-clear-btn" onClick={() => setCode('')}>Clear</button>
          )}
          <button
            className={`abap-run-btn ${mode === 'check' ? 'check' : 'generate'}`}
            onClick={mode === 'check' ? handleCheck : handleGenerate}
            disabled={!code.trim() || disabled}
          >
            {mode === 'check' ? '⌨ Check Code' : '✦ Generate'}
          </button>
        </div>
      </div>
    </div>
  )
}
