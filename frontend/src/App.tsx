import { useEffect, useState } from 'react'

type Health = { status: string }

export default function App() {
  const [health, setHealth] = useState<Health | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch('/api/health')
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        return res.json()
      })
      .then(setHealth)
      .catch((err) => setError(err.message))
  }, [])

  return (
    <main style={{ fontFamily: 'system-ui', padding: '2rem' }}>
      <h1>NetScope</h1>
      {error && <p style={{ color: 'crimson' }}>API unreachable: {error}</p>}
      {health && <p>API status: {health.status}</p>}
      {!health && !error && <p>Checking…</p>}
    </main>
  )
}