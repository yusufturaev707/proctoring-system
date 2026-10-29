import { useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import type { QueryClient } from '@tanstack/react-query'

import { tokens } from '../api/client'
import { auth } from '../api/endpoints'
import { CLOSE_FORBIDDEN, CLOSE_UNAUTHORIZED, WS_URL } from './useLiveMonitor'
import type { ApiRecord } from '../types/api'

/** Ro'yxat/son so'rovlarini yangilash oralig'i — har holat xabarida emas. */
const REFRESH_THROTTLE_MS = 3000

/** Kesh qiymatidagi qatorlarni (sahifa `results` yoki bitta yozuv) yangilaydi. */
function patchRows(data: unknown, byId: Map<number, ApiRecord>): { data: unknown; hit: boolean } {
  if (!data || typeof data !== 'object') return { data, hit: false }
  const record = data as ApiRecord
  if (Array.isArray(record.results)) {
    let hit = false
    const results = record.results.map((row: ApiRecord) => {
      const update = byId.get(row.id)
      if (!update) return row
      hit = true
      return { ...row, ...update }
    })
    return hit ? { data: { ...record, results }, hit } : { data, hit }
  }
  const update = typeof record.id === 'number' ? byId.get(record.id) : undefined
  return update ? { data: { ...record, ...update }, hit: true } : { data, hit: false }
}

function applyStatus(queryClient: QueryClient, rows: ApiRecord[]): boolean {
  const byId = new Map<number, ApiRecord>()
  for (const { region: _region, ...row } of rows) byId.set(row.id, row)
  const seen = new Set<number>()
  for (const key of [['bba-devices'], ['bba-device']]) {
    for (const [queryKey, data] of queryClient.getQueriesData({ queryKey: key })) {
      const result = patchRows(data, byId)
      if (!result.hit) continue
      queryClient.setQueryData(queryKey, result.data)
      const rowsOf = (result.data as ApiRecord).results ?? [result.data]
      for (const row of rowsOf as ApiRecord[]) if (byId.has(row.id)) seen.add(row.id)
    }
  }
  // Ekranda yo'q kompyuter (yangi yoki boshqa sahifada) — ro'yxatni qayta so'rash kerak.
  return rows.some((row) => !seen.has(row.id))
}

/**
 * BBA kompyuterlari holati real vaqtda (`ws/bba/`).
 *
 * Server Console'ni `BBA_STATUS_POLL_SECONDS` da bir so'raydi va faqat
 * O'ZGARGAN qatorlarni yuboradi. Ko'rinib turgan qatorlar keshda o'rnida
 * yangilanadi (jadval qayta so'ralmaydi); sonlar va ekranda yo'q
 * kompyuterlar uchun ro'yxat — `REFRESH_THROTTLE_MS` da bir marta.
 * Qayta ulanish va 4401/4403 qoidasi `useLiveMonitor` bilan bir xil.
 */
export function useBbaLive(enabled = true) {
  const queryClient = useQueryClient()
  const [connected, setConnected] = useState(false)
  const pendingRef = useRef<Set<string>>(new Set())
  const flushRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  useEffect(() => {
    if (!enabled) return undefined
    let socket: WebSocket | null = null
    let retry = 0
    let timer: ReturnType<typeof setTimeout> | undefined
    let disposed = false

    const schedule = (...keys: string[]) => {
      keys.forEach((key) => pendingRef.current.add(key))
      if (flushRef.current) return
      flushRef.current = setTimeout(() => {
        flushRef.current = undefined
        const keysToRefresh = [...pendingRef.current]
        pendingRef.current.clear()
        keysToRefresh.forEach((key) => queryClient.invalidateQueries({ queryKey: [key] }))
      }, REFRESH_THROTTLE_MS)
    }

    const connect = () => {
      const token = tokens.access()
      if (!token || disposed) return
      socket = new WebSocket(`${WS_URL}/ws/bba/?token=${encodeURIComponent(token)}`)

      socket.onmessage = (raw) => {
        let message: ApiRecord
        try {
          message = JSON.parse(raw.data)
        } catch {
          return
        }
        if (message.type === 'subscribed') {
          setConnected(true)
          retry = 0
        } else if (message.type === 'status' && Array.isArray(message.payload)) {
          const missing = applyStatus(queryClient, message.payload)
          schedule('bba-overview', 'bba-tree', ...(missing ? ['bba-devices'] : []))
        } else if (message.type === 'job') {
          schedule('bba-jobs', 'bba-device-jobs')
        }
      }

      socket.onclose = async (event) => {
        setConnected(false)
        if (disposed || event.code === CLOSE_FORBIDDEN) return
        if (event.code === CLOSE_UNAUTHORIZED) {
          try {
            await auth.me()
          } catch {
            // Interceptor token'ni yangilaydi yoki login'ga yuboradi.
          }
          if (disposed) return
        }
        const delay = Math.min(1000 * 2 ** retry, 30000)
        retry += 1
        timer = setTimeout(connect, delay)
      }

      socket.onerror = () => socket?.close()
    }

    connect()
    return () => {
      disposed = true
      clearTimeout(timer)
      clearTimeout(flushRef.current)
      flushRef.current = undefined
      if (socket) {
        socket.onclose = null
        socket.close()
      }
    }
  }, [enabled, queryClient])

  return { connected }
}
