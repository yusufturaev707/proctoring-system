import { useCallback, useEffect, useRef, useState } from 'react'
import { tokens } from '../api/client'

const WS_URL = import.meta.env.VITE_WS_URL || `ws://${window.location.hostname}:8001`

/**
 * Proktor dashboard'i uchun WebSocket ulanishi.
 *
 * Muhim detallar:
 *  - Avtomatik qayta ulanish EXPONENTIAL backoff bilan. Server qayta ishga
 *    tushganda 500 ta dashboard bir vaqtda urilsa, u yana yiqiladi.
 *  - Hodisalar buferi cheklangan (200 ta). Cheksiz massiv soatlab ochiq
 *    turgan brauzerda xotirani yeb qo'yadi.
 *  - Token query parametrida — brauzer WebSocket API'si header qo'shishga
 *    imkon bermaydi.
 */
export function useLiveMonitor({ zones = [], regions = [], enabled = true, maxEvents = 200 } = {}) {
  const [connected, setConnected] = useState(false)
  const [events, setEvents] = useState([])
  const [updates, setUpdates] = useState({})

  const socketRef = useRef(null)
  const retryRef = useRef(0)
  const timerRef = useRef(null)
  const subscriptionRef = useRef({ zones, regions })

  subscriptionRef.current = { zones, regions }

  const connect = useCallback(() => {
    const token = tokens.access()
    if (!token || !enabled) return

    const socket = new WebSocket(`${WS_URL}/ws/monitor/?token=${encodeURIComponent(token)}`)
    socketRef.current = socket

    socket.onopen = () => {
      setConnected(true)
      retryRef.current = 0
      const { zones: z, regions: r } = subscriptionRef.current
      socket.send(JSON.stringify({ action: 'subscribe', zones: z, regions: r }))
    }

    socket.onmessage = (raw) => {
      let message
      try {
        message = JSON.parse(raw.data)
      } catch {
        return
      }

      if (message.type === 'event') {
        setEvents((prev) => [
          { ...message.payload, receivedAt: Date.now() },
          ...prev.slice(0, maxEvents - 1),
        ])
      } else if (message.type === 'session_update') {
        setUpdates((prev) => ({ ...prev, [message.payload.session_id]: message.payload }))
      }
    }

    socket.onclose = () => {
      setConnected(false)
      if (!enabled) return
      // 1s, 2s, 4s, 8s ... maksimum 30s.
      const delay = Math.min(1000 * 2 ** retryRef.current, 30000)
      retryRef.current += 1
      timerRef.current = setTimeout(connect, delay)
    }

    socket.onerror = () => socket.close()
  }, [enabled, maxEvents])

  useEffect(() => {
    connect()
    return () => {
      clearTimeout(timerRef.current)
      const socket = socketRef.current
      if (socket) {
        socket.onclose = null
        socket.close()
      }
    }
  }, [connect])

  // Obuna o'zgarganda serverga xabar beramiz (qayta ulanmasdan).
  useEffect(() => {
    const socket = socketRef.current
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ action: 'subscribe', zones, regions }))
    }
  }, [zones.join(','), regions.join(',')]) // eslint-disable-line react-hooks/exhaustive-deps

  const clearEvents = useCallback(() => setEvents([]), [])

  return { connected, events, updates, clearEvents }
}
