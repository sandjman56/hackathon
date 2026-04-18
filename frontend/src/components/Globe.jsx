import { useEffect, useRef } from 'react'
import { GLOBE_LAND } from './globe_data.js'

const AUTO_SPEED = 4   // degrees/second
const RESUME_DELAY = 1800  // ms after drag release before auto-spin resumes

// Keyframes injected once
const GLOBE_CSS = `
@keyframes mk-pulse {
  0%   { transform: translate(-50%, -50%) scale(1); opacity: 0.7; }
  100% { transform: translate(-50%, -50%) scale(2.8); opacity: 0; }
}
`
if (typeof document !== 'undefined') {
  const existing = document.getElementById('globe-css')
  if (!existing) {
    const s = document.createElement('style')
    s.id = 'globe-css'
    s.textContent = GLOBE_CSS
    document.head.appendChild(s)
  }
}

function parseCoordinates(coordStr) {
  if (!coordStr) return null
  const parts = coordStr.split(',').map((s) => parseFloat(s.trim()))
  if (parts.length !== 2 || parts.some(isNaN)) return null
  return { lat: parts[0], lon: parts[1] }
}

export default function Globe({ projectName, coordinates, size = 220 }) {
  const canvasRef = useRef(null)
  const markerRef = useRef(null)
  const stateRef = useRef({
    centerLon: -80,
    centerLat: 20,
    dragging: false,
    lastT: 0,
    resumeAt: 0,
    pointerId: null,
    lastX: 0,
    lastY: 0,
    rafId: null,
  })

  const target = parseCoordinates(coordinates) || { lat: 40.4406, lon: -79.9959 }
  const targetName = projectName || 'PROJECT SITE'

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    const W = canvas.width
    const H = canvas.height
    const R = W * 0.47
    const st = stateRef.current

    function project(lon, lat) {
      const λ0 = st.centerLon * Math.PI / 180
      const φ0 = st.centerLat * Math.PI / 180
      const cosφ0 = Math.cos(φ0), sinφ0 = Math.sin(φ0)
      const λ = lon * Math.PI / 180 - λ0
      const φ = lat * Math.PI / 180
      const cosφ = Math.cos(φ), sinφ = Math.sin(φ)
      const cosC = sinφ0 * sinφ + cosφ0 * cosφ * Math.cos(λ)
      const x = R * cosφ * Math.sin(λ)
      const y = R * (cosφ0 * sinφ - sinφ0 * cosφ * Math.cos(λ))
      return { on: cosC >= 0, x: W / 2 + x, y: H / 2 - y, angle: Math.atan2(-y, x) }
    }

    function findCrossing(lon1, lat1, lon2, lat2) {
      const toXYZ = (lon, lat) => {
        const λ = lon * Math.PI / 180, φ = lat * Math.PI / 180
        return [Math.cos(φ) * Math.cos(λ), Math.cos(φ) * Math.sin(λ), Math.sin(φ)]
      }
      const a = toXYZ(lon1, lat1), b = toXYZ(lon2, lat2)
      const dot = a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
      const omega = Math.acos(Math.max(-1, Math.min(1, dot)))
      const sinO = Math.sin(omega) || 1
      let lo = 0, hi = 1
      for (let i = 0; i < 18; i++) {
        const t = (lo + hi) / 2
        const s1 = Math.sin((1 - t) * omega) / sinO, s2 = Math.sin(t * omega) / sinO
        const x = s1 * a[0] + s2 * b[0]
        const y = s1 * a[1] + s2 * b[1]
        const z = s1 * a[2] + s2 * b[2]
        const lat = Math.atan2(z, Math.hypot(x, y)) * 180 / Math.PI
        const lon = Math.atan2(y, x) * 180 / Math.PI
        if (project(lon, lat).on) lo = t; else hi = t
      }
      const t = (lo + hi) / 2
      const s1 = Math.sin((1 - t) * omega) / sinO, s2 = Math.sin(t * omega) / sinO
      const x = s1 * a[0] + s2 * b[0]
      const y = s1 * a[1] + s2 * b[1]
      const z = s1 * a[2] + s2 * b[2]
      const lat = Math.atan2(z, Math.hypot(x, y)) * 180 / Math.PI
      const lon = Math.atan2(y, x) * 180 / Math.PI
      return project(lon, lat)
    }

    const limbAngle = (x, y) => Math.atan2(y - H / 2, x - W / 2)

    function render() {
      ctx.clearRect(0, 0, W, H)

      // outer halo
      const halo = ctx.createRadialGradient(W / 2, H / 2, R * 0.95, W / 2, H / 2, R * 1.18)
      halo.addColorStop(0, 'rgba(0,255,135,0)')
      halo.addColorStop(0.5, 'rgba(0,255,135,0.06)')
      halo.addColorStop(1, 'rgba(0,255,135,0)')
      ctx.fillStyle = halo
      ctx.beginPath(); ctx.arc(W / 2, H / 2, R * 1.18, 0, Math.PI * 2); ctx.fill()

      // ocean
      ctx.save()
      ctx.beginPath(); ctx.arc(W / 2, H / 2, R, 0, Math.PI * 2); ctx.clip()
      const og = ctx.createRadialGradient(W / 2 - R * 0.4, H / 2 - R * 0.5, R * 0.1, W / 2, H / 2, R)
      og.addColorStop(0, '#0f3f38')
      og.addColorStop(0.45, '#092218')
      og.addColorStop(1, '#020a07')
      ctx.fillStyle = og
      ctx.fillRect(0, 0, W, H)

      // continents
      ctx.fillStyle = 'rgba(6,26,20,0.92)'
      ctx.strokeStyle = 'rgba(0,255,135,0.28)'
      ctx.lineWidth = 0.5

      for (const poly of GLOBE_LAND) {
        const N = poly.length
        const projected = new Array(N)
        for (let i = 0; i < N; i++) projected[i] = project(poly[i][0], poly[i][1])

        const runs = []
        let cur = null
        const flushCur = () => { if (cur && cur.pts.length >= 2) runs.push(cur); cur = null }

        for (let i = 0; i < N; i++) {
          const a = projected[i]
          const b = projected[(i + 1) % N]
          const [alon, alat] = poly[i]
          const [blon, blat] = poly[(i + 1) % N]
          const dLon = Math.abs(blon - alon)
          // Natural Earth 110m coordinates are in [-180,180]; a raw delta > 180° reliably identifies antimeridian segments
          const antiSplit = dLon > 180

          if (a.on) {
            if (!cur) cur = { pts: [], startOnLimb: false, endOnLimb: false }
            if (cur.pts.length === 0 ||
              cur.pts[cur.pts.length - 1].x !== a.x ||
              cur.pts[cur.pts.length - 1].y !== a.y) {
              cur.pts.push({ x: a.x, y: a.y })
            }
          }

          if (antiSplit) {
            if (cur) { cur.endOnLimb = false; flushCur() }
            continue
          }

          if (a.on && !b.on) {
            const c = findCrossing(alon, alat, blon, blat)
            cur.pts.push({ x: c.x, y: c.y })
            cur.endOnLimb = true
            flushCur()
          } else if (!a.on && b.on) {
            const c = findCrossing(blon, blat, alon, alat)
            cur = { pts: [{ x: c.x, y: c.y }], startOnLimb: true, endOnLimb: false }
          }
        }

        if (cur) {
          if (runs.length > 0 && !runs[0].startOnLimb && !cur.endOnLimb) {
            const first = runs.shift()
            cur.pts.push(...first.pts)
            cur.endOnLimb = first.endOnLimb
          }
          flushCur()
        }

        if (runs.length === 0) continue
        ctx.beginPath()
        ctx.moveTo(runs[0].pts[0].x, runs[0].pts[0].y)
        for (let r = 0; r < runs.length; r++) {
          const run = runs[r]
          if (r > 0) {
            const prev = runs[r - 1].pts[runs[r - 1].pts.length - 1]
            const a1 = limbAngle(prev.x, prev.y)
            const a2 = limbAngle(run.pts[0].x, run.pts[0].y)
            let delta = a2 - a1
            while (delta > Math.PI) delta -= 2 * Math.PI
            while (delta < -Math.PI) delta += 2 * Math.PI
            ctx.arc(W / 2, H / 2, R, a1, a1 + delta, delta < 0)
          }
          for (let i = 1; i < run.pts.length; i++) {
            ctx.lineTo(run.pts[i].x, run.pts[i].y)
          }
        }

        const lastPt = runs[runs.length - 1].pts[runs[runs.length - 1].pts.length - 1]
        const firstPt = runs[0].pts[0]
        const a1 = limbAngle(lastPt.x, lastPt.y)
        const a2 = limbAngle(firstPt.x, firstPt.y)
        const closeOnLimb = runs[0].startOnLimb && runs[runs.length - 1].endOnLimb
        if (closeOnLimb) {
          let delta = a2 - a1
          while (delta > Math.PI) delta -= 2 * Math.PI
          while (delta < -Math.PI) delta += 2 * Math.PI
          ctx.arc(W / 2, H / 2, R, a1, a1 + delta, delta < 0)
        }
        ctx.closePath()
        ctx.fill()
        ctx.stroke()
      }

      // dark side shadow
      const ig = ctx.createRadialGradient(W / 2 - R * 0.4, H / 2 - R * 0.4, R * 0.2, W / 2, H / 2, R)
      ig.addColorStop(0, 'rgba(0,0,0,0)')
      ig.addColorStop(0.6, 'rgba(0,0,0,0.25)')
      ig.addColorStop(1, 'rgba(0,0,0,0.72)')
      ctx.fillStyle = ig
      ctx.fillRect(0, 0, W, H)

      // sheen
      const sh = ctx.createRadialGradient(W / 2 - R * 0.45, H / 2 - R * 0.55, 0, W / 2 - R * 0.45, H / 2 - R * 0.55, R * 0.9)
      sh.addColorStop(0, 'rgba(0,255,135,0.11)')
      sh.addColorStop(1, 'rgba(0,255,135,0)')
      ctx.fillStyle = sh
      ctx.fillRect(0, 0, W, H)
      ctx.restore()

      // rim
      ctx.beginPath(); ctx.arc(W / 2, H / 2, R, 0, Math.PI * 2)
      ctx.strokeStyle = 'rgba(0,255,135,0.45)'
      ctx.lineWidth = 0.8
      ctx.stroke()

      // position marker — read ref each frame so stale closure can't touch a detached node
      const p = project(target.lon, target.lat)
      const marker = markerRef.current
      if (marker && canvasRef.current) {
        if (p.on) {
          marker.style.display = 'block'
          marker.style.left = p.x + 'px'
          marker.style.top = p.y + 'px'
        } else {
          marker.style.display = 'none'
        }
      }
    }

    function tick(now) {
      if (!canvasRef.current) return
      const dt = Math.min(64, now - st.lastT) / 1000
      st.lastT = now
      if (!st.dragging && now >= st.resumeAt) {
        st.centerLon += AUTO_SPEED * dt
        if (st.centerLon > 180) st.centerLon -= 360
        if (st.centerLon < -180) st.centerLon += 360
      }
      render()
      st.rafId = requestAnimationFrame(tick)
    }

    st.lastT = performance.now()
    st.rafId = requestAnimationFrame(tick)

    // drag
    const DRAG_LON = 180 / (W * 0.9)
    const DRAG_LAT = 140 / (H * 0.9)

    const onDown = (e) => {
      st.dragging = true
      st.pointerId = e.pointerId
      st.lastX = e.clientX
      st.lastY = e.clientY
      canvas.setPointerCapture(e.pointerId)
      canvas.style.cursor = 'grabbing'
    }
    const onMove = (e) => {
      if (!st.dragging || e.pointerId !== st.pointerId) return
      const dx = e.clientX - st.lastX
      const dy = e.clientY - st.lastY
      st.lastX = e.clientX
      st.lastY = e.clientY
      st.centerLon -= dx * DRAG_LON
      st.centerLat += dy * DRAG_LAT
      if (st.centerLat > 82) st.centerLat = 82
      if (st.centerLat < -82) st.centerLat = -82
      if (st.centerLon > 180) st.centerLon -= 360
      if (st.centerLon < -180) st.centerLon += 360
    }
    const onUp = (e) => {
      if (!st.dragging || e.pointerId !== st.pointerId) return
      st.dragging = false
      try { canvas.releasePointerCapture(st.pointerId) } catch (_) { }
      st.pointerId = null
      canvas.style.cursor = 'grab'
      st.resumeAt = performance.now() + RESUME_DELAY
    }

    canvas.addEventListener('pointerdown', onDown)
    canvas.addEventListener('pointermove', onMove)
    canvas.addEventListener('pointerup', onUp)
    canvas.addEventListener('pointercancel', onUp)
    canvas.style.cursor = 'grab'
    canvas.style.touchAction = 'none'

    return () => {
      if (st.rafId) cancelAnimationFrame(st.rafId)
      canvas.removeEventListener('pointerdown', onDown)
      canvas.removeEventListener('pointermove', onMove)
      canvas.removeEventListener('pointerup', onUp)
      canvas.removeEventListener('pointercancel', onUp)
    }
  }, [target.lat, target.lon, size])

  const ns = target.lat >= 0 ? 'N' : 'S'
  const ew = target.lon >= 0 ? 'E' : 'W'
  const coordStr = `${Math.abs(target.lat).toFixed(4)}°${ns} · ${Math.abs(target.lon).toFixed(4)}°${ew}`

  return (
    <div style={{ ...styles.container, width: size, height: size }}>
      {/* Stars */}
      <div style={styles.stars} />

      {/* Canvas */}
      <canvas
        ref={canvasRef}
        width={size}
        height={size}
        style={styles.canvas}
        aria-label="Interactive globe showing project location"
      />

      {/* CSS target marker */}
      <div ref={markerRef} style={styles.marker}>
        <span style={styles.dot} />
        <span style={styles.ringR1} />
        <span style={styles.pulse} />
        <span style={{ ...styles.pulse, animationDelay: '1.2s' }} />
        <span style={{ ...styles.tick, ...styles.tickHL }} />
        <span style={{ ...styles.tick, ...styles.tickHR }} />
        <span style={{ ...styles.tick, ...styles.tickVT }} />
        <span style={{ ...styles.tick, ...styles.tickVB }} />
        <div style={styles.callout}>
          <div style={styles.calloutName}>{targetName.toUpperCase()}</div>
          <div style={styles.calloutCoord}>{coordStr}</div>
        </div>
      </div>

      {/* HUD */}
      <div style={{ ...styles.hud, top: 10, left: 12 }}>◉ TARGET ACQUIRED</div>
      <div style={{ ...styles.hud, bottom: 10, left: 12, color: '#888', letterSpacing: '1px' }}>{coordStr}</div>
    </div>
  )
}

const styles = {
  container: {
    position: 'relative',
    flexShrink: 0,
    background: 'radial-gradient(ellipse at 50% 50%, #051210 0%, #030a08 55%, #010604 100%)',
    borderRadius: '8px',
    overflow: 'hidden',
  },
  stars: {
    position: 'absolute',
    inset: 0,
    pointerEvents: 'none',
    backgroundImage: [
      'radial-gradient(1px 1px at 12% 18%, #f0f0f0 50%, transparent 51%)',
      'radial-gradient(1px 1px at 28% 72%, #d0d0d0 50%, transparent 51%)',
      'radial-gradient(1px 1px at 45% 36%, #f0f0f0 50%, transparent 51%)',
      'radial-gradient(1px 1px at 62% 84%, #d0d0d0 50%, transparent 51%)',
      'radial-gradient(1px 1px at 75% 22%, #f0f0f0 50%, transparent 51%)',
      'radial-gradient(1px 1px at 88% 58%, #d0d0d0 50%, transparent 51%)',
      'radial-gradient(2px 2px at 18% 48%, #f0f0f0 50%, transparent 51%)',
      'radial-gradient(1px 1px at 52% 66%, #d0d0d0 50%, transparent 51%)',
    ].join(','),
    opacity: 0.5,
  },
  canvas: {
    display: 'block',
    position: 'absolute',
    inset: 0,
  },
  marker: {
    position: 'absolute',
    pointerEvents: 'none',
    transform: 'translate(-50%, -50%)',
    width: 0,
    height: 0,
  },
  dot: {
    position: 'absolute',
    left: -4,
    top: -4,
    width: 8,
    height: 8,
    borderRadius: '50%',
    background: '#00ff87',
    boxShadow: '0 0 12px #00ff87, 0 0 4px #00ff87',
  },
  ringR1: {
    position: 'absolute',
    border: '1px solid #00ff87',
    borderRadius: '50%',
    opacity: 0.7,
    left: -11,
    top: -11,
    width: 22,
    height: 22,
  },
  pulse: {
    position: 'absolute',
    border: '1.5px solid #00ff87',
    borderRadius: '50%',
    animation: 'mk-pulse 2.4s ease-out infinite',
    left: -14,
    top: -14,
    width: 28,
    height: 28,
  },
  tick: {
    position: 'absolute',
    background: '#00ff87',
    boxShadow: '0 0 4px #00ff87',
  },
  tickHL: { width: 8, height: 1, left: -20, top: -0.5 },
  tickHR: { width: 8, height: 1, left: 12, top: -0.5 },
  tickVT: { width: 1, height: 8, left: -0.5, top: -20 },
  tickVB: { width: 1, height: 8, left: -0.5, top: 12 },
  callout: {
    position: 'absolute',
    transform: 'translate(28px, -22px)',
    fontFamily: 'var(--font-mono)',
    whiteSpace: 'nowrap',
    pointerEvents: 'none',
  },
  calloutName: {
    fontSize: 9,
    color: '#00ff87',
    letterSpacing: '1.5px',
    marginBottom: 2,
    fontWeight: 500,
  },
  calloutCoord: {
    fontSize: 8,
    color: '#a5d6b8',
    letterSpacing: '0.5px',
  },
  hud: {
    position: 'absolute',
    fontFamily: 'var(--font-mono)',
    fontSize: 8,
    letterSpacing: '1.5px',
    color: '#00ff87',
    zIndex: 5,
    pointerEvents: 'none',
  },
}
