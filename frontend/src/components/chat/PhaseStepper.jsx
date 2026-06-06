const PHASES = [
  { key: 'routing_query',    label: 'Understanding' },
  { key: 'calling_tool',     label: 'Retrieving' },
  { key: 'fetching_data',    label: 'Fetching' },
  { key: 'processing',       label: 'Processing' },
  { key: 'streaming_answer', label: 'Generating' },
]

export default function PhaseStepper({ currentPhase, done, durationMs }) {
  if (done && durationMs != null) {
    return (
      <div className="phase-stepper phase-stepper--done">
        <span className="phase-step-icon phase-step-icon--complete">✓</span>
        <span className="phase-stepper-summary">Done in {(durationMs / 1000).toFixed(1)}s</span>
      </div>
    )
  }

  const activeIdx = PHASES.findIndex((p) => p.key === currentPhase)

  return (
    <div className="phase-stepper">
      {PHASES.map((phase, idx) => {
        const isComplete = activeIdx > idx
        const isActive   = activeIdx === idx
        const isPending  = activeIdx < idx
        return (
          <div
            key={phase.key}
            className={[
              'phase-step',
              isActive   ? 'phase-step--active'   : '',
              isComplete ? 'phase-step--complete' : '',
              isPending  ? 'phase-step--pending'  : '',
            ].join(' ').trim()}
          >
            <span className="phase-step-icon">
              {isComplete ? '✓' : isActive ? '●' : '○'}
            </span>
            <span className="phase-step-label">{phase.label}</span>
            {idx < PHASES.length - 1 && <span className="phase-step-connector" />}
          </div>
        )
      })}
    </div>
  )
}
