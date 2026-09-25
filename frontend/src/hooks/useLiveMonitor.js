import { useCallback, useEffect, useRef, useState } from 'react'
import { tokens } from '../api/client'
import { auth } from '../api/endpoints'

// STANDART — SAHIFANING O'Z MANZILI (`/ws/` ni production'da nginx, dev'da
// Vite proxy uzatadi). Ilgari `ws://<host>:8001` edi: HTTPS sahifada brauzer
// shifrlanmagan `ws://` ni bloklaydi (mixed content) va jonli kuzatuv
// production'da umuman ulanmasdi, 8001-port esa tashqariga ochiq bo'lishi
// kerak bo'lib qolardi. Boshqa host kerak bo'lsa — `VITE_WS_URL`.
const WS_URL =
  import.meta.env.VITE_WS_URL ||
  `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}`

// Backend `consumers.py` dagi yopilish kodlari.
const CLOSE_UNAUTHORIZED = 4401
const CLOSE_FORBIDDEN = 4403

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
 *  - "Ulangan" = OBUNA TASDIQLANGAN (`subscribed`), socket ochilgani emas.
 *    Server obunada yiqilsa socket ochilib darhol yopiladi; ilgari
 *    panel shu oraliqda "ulangan" ko'rsatar va backoff har ochilishda
 *    nolga tushib, 1 soniyali cheksiz siklga aylanardi.
 *  - 4401 (token eskirgan) — avval token yangilanadi: eski token bilan
 *    qayta urinish hech qachon o'tmaydi. 4403 — qayta urinilmaydi.
 */
export function useLiveMonitor({ zones = [], regions = [], enabled = true, maxEvents = 200 } = {}) {
  const [connected, setConnected] = useState(false)
  const [events, setEvents] = useState([])
  const [updates, setUpdates] = useState({})

  const socketRef = useRef(null)
  const retryRef = useRef(0)
  const timerRef = useRef(null)
  const subscriptionRef = useRef({ zones, regions })
  const disposedRef = useRef(false)

  subscriptionRef.current = { zones, regions }

  const connect = useCallback(() => {
    const token = tokens.access()
    if (!token || !enabled) return

    const socket = new WebSocket(`${WS_URL}/ws/monitor/?token=${encodeURIComponent(token)}`)
    socketRef.current = socket

    socket.onopen = () => {
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

      if (message.type === 'subscribed') {
        setConnected(true)
        retryRef.current = 0
      } else if (message.type === 'event') {
        setEvents((prev) => [
          { ...message.payload, receivedAt: Date.now() },
          ...prev.slice(0, maxEvents - 1),
        ])
      } else if (message.type === 'session_update') {
        setUpdates((prev) => ({ ...prev, [message.payload.session_id]: message.payload }))
      }
    }

    socket.onclose = async (closeEvent) => {
      setConnected(false)
      if (!enabled || disposedRef.current) return
      if (closeEvent.code === CLOSE_FORBIDDEN) return

      if (closeEvent.code === CLOSE_UNAUTHORIZED) {
        // Oddiy autentifikatsiyali so'rov axios interceptor'i orqali
        // tokenni yangilaydi (refresh ham eskirgan bo'lsa — login'ga).
        try {
          await auth.me()
        } catch {
          // Interceptor o'zi hal qiladi; qayta urinish backoff bilan.
        }
        if (disposedRef.current) return
      }

      // 1s, 2s, 4s, 8s ... maksimum 30s.
      const delay = Math.min(1000 * 2 ** retryRef.current, 30000)
      retryRef.current += 1
      timerRef.current = setTimeout(connect, delay)
    }

    socket.onerror = () => socket.close()
  }, [enabled, maxEvents])

  useEffect(() => {
    disposedRef.current = false
    connect()
    return () => {
      disposedRef.current = true
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
