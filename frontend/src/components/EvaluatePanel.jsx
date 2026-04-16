export default function EvaluatePanel() {
  return (
    <div style={styles.container}>
      <div style={styles.label}>EVALUATION</div>
      <p style={styles.hint}>Run evaluation against imported pipeline data</p>
      <button
        style={styles.evalBtn}
        onClick={() => {}}
      >
        EVALUATE
      </button>
    </div>
  )
}

const styles = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    height: '100%',
    gap: '16px',
    padding: '24px',
  },
  label: {
    fontFamily: 'var(--font-mono)',
    fontSize: '11px',
    color: 'var(--green-primary)',
    letterSpacing: '3px',
  },
  hint: {
    fontFamily: 'var(--font-mono)',
    fontSize: '10px',
    color: 'var(--text-muted)',
    textAlign: 'center',
    margin: 0,
  },
  evalBtn: {
    fontFamily: 'var(--font-mono)',
    fontSize: '11px',
    letterSpacing: '2px',
    color: '#0a0a0a',
    background: 'var(--green-primary)',
    border: '1px solid var(--green-primary)',
    borderRadius: '4px',
    padding: '10px 28px',
    cursor: 'pointer',
    fontWeight: 600,
  },
}
