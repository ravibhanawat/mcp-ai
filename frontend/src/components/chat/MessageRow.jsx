import { useState } from 'react'
import MarkdownRenderer from '../ui/MarkdownRenderer.jsx'
import ReportWidget from '../../ReportWidget.jsx'
import { AbapReviewWidget, AbapCodeWidget } from '../../AbapWidget.jsx'
import ReceiptWidget from '../../ReceiptWidget.jsx'
import useChatStore from '../../stores/chat-store.js'

// ─── Inline icon helpers ──────────────────────────────────────────────────────

function Svg({ size = 16, children }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      {children}
    </svg>
  )
}

function IconClavis() {
  return (
    <Svg size={18}>
      <path d="M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2Z" />
    </Svg>
  )
}

function IconBeaker() {
  return (
    <Svg>
      <path d="M4.5 3h15" />
      <path d="M6 3v16a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V3" />
      <path d="M6 14h12" />
    </Svg>
  )
}

// ─── MessageRow ───────────────────────────────────────────────────────────────

export default function MessageRow({ msg, SapSourceBadge, ResearchReport, Plan }) {
  const [copied, setCopied] = useState(false)
  const isUser = msg.role === 'user'
  const setDataPanel = useChatStore(s => s.setDataPanel)

  // Kutty ticket-backlog sources (when this turn used the ticket-search tool)
  const kuttyTickets = (!isUser && msg.done?.tool_called === 'search_sap_tickets')
    ? (msg.done?.tool_result?.tickets || [])
    : []

  const viewTickets = () => {
    setDataPanel({
      mode: 'data',
      title: 'Kutty — Tickets',
      rows: {
        columns: ['Ticket ID', 'Title', 'Module', 'Project', 'Status'],
        rows: kuttyTickets.map(t => ({
          'Ticket ID': t.ticket_id, 'Title': t.title,
          'Module': t.module, 'Project': t.project, 'Status': t.status,
        })),
        row_count: kuttyTickets.length,
      },
    })
  }

  const doCopy = () => {
    navigator.clipboard.writeText(msg.content || '')
    setCopied(true)
    setTimeout(() => setCopied(false), 1800)
  }

  return (
    <div className={`msg-row ${isUser ? 'user' : 'bot'}`}>
      <div className={`msg-avatar ${isUser ? 'user-av' : 'bot-av'}`}>
        {isUser
          ? (msg.userInitial || 'U')
          : msg.research_mode
            ? <IconBeaker />
            : <IconClavis />
        }
      </div>
      <div className="msg-body">

        {/* Reasoning steps — collapsed details with styled step track */}
        {!isUser && msg.status_steps?.length > 0 && (
          <details className="stream-steps-collapsed">
            <summary>Reasoning — {msg.status_steps.length} step{msg.status_steps.length !== 1 ? 's' : ''}</summary>
            <div className="step-track">
              {msg.status_steps.map((s, i) => (
                <div key={i} className="step-track-item">
                  <div className="step-dot-wrap"><div className="step-dot-done" /></div>
                  <span className="step-track-text">{s}</span>
                </div>
              ))}
            </div>
          </details>
        )}

        {/* Message content */}
        {msg.research_mode ? (
          <ResearchReport result={msg.research_result} />
        ) : isUser ? (
          <div className="msg-bubble">{msg.content}</div>
        ) : (
          <div className="msg-bubble md-bubble">
            <MarkdownRenderer content={msg.content} />
          </div>
        )}

        {/* Meta badges */}
        <div className="msg-meta">
          {msg.research_mode && <span className="badge badge-research">AUTO RESEARCH</span>}
          {kuttyTickets.length > 0 && <span className="badge badge-research">KUTTY · {kuttyTickets.length} TICKETS</span>}
        </div>

        {/* SAP source */}
        {!msg.research_mode && msg.sap_source && <SapSourceBadge source={msg.sap_source} />}

        {/* Kutty ticket sources */}
        {kuttyTickets.length > 0 && (
          <div className="kutty-sources">
            <div className="kutty-sources-head">
              <span>Tickets cited</span>
              <button className="btn-ghost" onClick={viewTickets}>View tickets</button>
            </div>
            <ul className="kutty-source-list">
              {kuttyTickets.map((t, i) => (
                <li key={t.ticket_id || i} className="kutty-source-item">
                  {t.ticket_id && <code className="kutty-tid">#{t.ticket_id}</code>}
                  <span className="kutty-title">{t.title || '(untitled)'}</span>
                  {t.status && <span className="kutty-status-chip">{t.status}</span>}
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Data badge — rows fetched during this turn */}
        {msg.rows?.columns?.length > 0 && (
          <div className="data-badge">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <rect width="18" height="18" x="3" y="3" rx="2" /><path d="M3 9h18" /><path d="M9 21V9" />
            </svg>
            <span>{msg.rows.row_count ?? msg.rows.rows?.length ?? 0} records</span>
            <button className="btn-ghost" onClick={() => setDataPanel({ rows: msg.rows, title: msg.rows.tool || 'Query Results' })}>
              View Data
            </button>
          </div>
        )}

        {/* Other widgets */}
        {msg.report && <ReportWidget report={msg.report} />}
        {msg.abap_check && <AbapReviewWidget abap_check={msg.abap_check} />}
        {msg.abap_code && <AbapCodeWidget abap_code={msg.abap_code} />}
        {msg.tool_result && (msg.tool_result.outstanding_items || msg.tool_result.park_reference) && (
          <ReceiptWidget initialData={msg.tool_result.outstanding_items ? msg.tool_result : null} />
        )}
        {(msg.tool_called === "autonomous_agent" || msg.tool_called === "action_plan" || msg.action_plan) && (
          <Plan planData={msg.action_plan} />
        )}

        {/* Action bar — bot messages only */}
        {!isUser && (
          <div className="action-bar">
            <button className={`btn-ghost ${copied ? 'copied' : ''}`} onClick={doCopy}>
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <rect width="14" height="14" x="8" y="8" rx="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>
              </svg>
              {copied ? 'Copied!' : 'Copy'}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
