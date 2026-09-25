import { useCallback, useEffect, useState } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'

/** Kursorli javobdagi `next`/`previous` havolasidan kursorning o'zi. */
export function cursorFrom(link) {
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
export function useCursorPages({ key, fetchPage, enabled = true, initialPageSize = 50 }) {
  const [pageSize, setPageSizeState] = useState(initialPageSize)
  // stack[i] — i-sahifaning kursori; birinchi sahifa kursorsiz.
  const [stack, setStack] = useState([null])
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
  const setPageSize = useCallback((size) => {
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
    },
  }
}
