import { useCallback, useEffect, useState } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import type { ApiRecord } from '../types/api'

/** `TablePager` (DataTable futeri) kutadigan kursorli navigatsiya. */
export interface CursorNav {
  hasNext: boolean
  hasPrevious: boolean
  onNext: () => void
  onPrevious: () => void
  pageIndex: number
  pageSize: number
  onPageSizeChange: (size: number) => void
}

/** `fetchPage` natijasi. Kursor ixtiyoriy qiymat (satr yoki obyekt). */
export interface CursorPage {
  results: ApiRecord[]
  nextCursor?: unknown
}

export interface UseCursorPagesOptions {
  key: unknown[]
  fetchPage: (args: { cursor: unknown; pageSize: number }) => Promise<CursorPage>
  enabled?: boolean
  initialPageSize?: number
}

/** Kursorli javobdagi `next`/`previous` havolasidan kursorning o'zi. */
export function cursorFrom(link: string | null | undefined): string | null {
  if (!link) return null
  try {
    return new URL(link, window.location.origin).searchParams.get('cursor')
  } catch {
    return null
  }
}

/**
 * Kursorli ro'yxat (sessiya tafsilotidagi tab'lar).
 *
 * NIMA UCHUN KURSOR, raqamli sahifa emas: hodisa, skrinshot va dalil
 * jadvallari eng tez o'sadiganlar (sessiyaga yuzlab qator) va server
 * ularda `COUNT(*)` qilmaydi (`EventCursorPagination`). Kursor esa
 * indeks bo'yicha "shu nuqtadan keyingi N ta" deydi — 50-sahifa ham
 * birinchisidek tez. Narxi: "7-sahifaga o'tish" yo'q, faqat
 * oldinga/orqaga; tafsilot sahifasida bu yetarli.
 *
 * Ilgari har tab faqat BIRINCHI sahifani so'rardi (100/60/40 ta) va
 * qolgani JIMGINA ko'rinmasdi — 500 hodisali sessiyada proktor 100
 * tasini ko'rib, "hammasi shu" deb o'ylardi.
 *
 * `fetchPage({ cursor, pageSize })` -> `{ results, nextCursor }`.
 * Kursor ixtiyoriy qiymat (satr yoki obyekt): skrinshotlarda u ikki
 * manbaning juftligi.
 */
export function useCursorPages({ key, fetchPage, enabled = true, initialPageSize = 50 }: UseCursorPagesOptions) {
  const [pageSize, setPageSizeState] = useState(initialPageSize)
  // stack[i] — i-sahifaning kursori; birinchi sahifa kursorsiz.
  const [stack, setStack] = useState<unknown[]>([null])
  const cursor = stack[stack.length - 1]
  const keyString = JSON.stringify(key)

  // Boshqa ro'yxatga (boshqa sessiyaga) o'tilsa — birinchi sahifadan.
  useEffect(() => { setStack([null]) }, [keyString])

  const query = useQuery({
    queryKey: [...key, pageSize, cursor],
    queryFn: () => fetchPage({ cursor, pageSize }),
    enabled,
    // Sahifa almashganda ro'yxat BO'SHAMAYDI — eski qatorlar yangisi
    // kelguncha turadi (`useResource` dagi bilan bir xil).
    placeholderData: keepPreviousData,
  })

  const nextCursor = query.data?.nextCursor || null

  const next = useCallback(() => {
    if (nextCursor) setStack((prev) => [...prev, nextCursor])
  }, [nextCursor])
  const previous = useCallback(() => {
    setStack((prev) => (prev.length > 1 ? prev.slice(0, -1) : prev))
  }, [])
  const setPageSize = useCallback((size: number) => {
    setPageSizeState(size)
    setStack([null])
  }, [])

  const pageIndex = stack.length - 1
  return {
    rows: query.data?.results || [],
    isLoading: query.isLoading,
    isFetching: query.isFetching,
    error: query.error,
    refetch: query.refetch,
    pageIndex,
    pageSize,
    offset: pageIndex * pageSize,
    // `TablePager` (DataTable futeri) kutadigan shakl.
    cursorNav: {
      hasNext: Boolean(nextCursor),
      hasPrevious: pageIndex > 0,
      onNext: next,
      onPrevious: previous,
      pageIndex,
      pageSize,
      onPageSizeChange: setPageSize,
    } satisfies CursorNav,
  }
}
