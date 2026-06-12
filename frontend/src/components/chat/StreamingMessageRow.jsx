import PhaseStepper from './PhaseStepper.jsx'

const Svg = ({ size = 16, children }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">{children}</svg>
)

const IconClavis = () => <Svg size={18}><path d="M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2Z" /></Svg>

function ShiningText({ text }) {
  return <span className="shining-text">{text}</span>
}

export default function StreamingMessageRow({ msg, Plan }) {
  return (
    <div className="msg-row bot">
      <div className="msg-avatar bot-av">
        <IconClavis />
      </div>
      <div className="msg-body">

        {msg.status_steps?.length > 0 && (
          <PhaseStepper
            currentPhase={msg.currentPhase || null}
            done={false}
            durationMs={null}
          />
        )}

        {msg.content ? (
          <div className="msg-bubble" style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
            {msg.content}
          </div>
        ) : (
          <div className="stream-thinking">
            <ShiningText text="Kutty is thinking..." />
          </div>
        )}

        {(msg.tool_called === "autonomous_agent" || msg.tool_called === "action_plan" || msg.action_plan) && Plan && (
          <Plan planData={msg.action_plan} />
        )}
      </div>
    </div>
  )
}
