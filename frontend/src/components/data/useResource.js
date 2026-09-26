import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useUi } from '../../context/UiContext'

/** Qidiruvni kechiktiradi — har bir harfda so'rov ketmasligi uchun. */
export function useDebounced(value, delay = 350) {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay)
    return () => clearTimeout(timer)
  }, [value, delay])
  return debounced
}

/**
 * Jadval holatini URL'ga bog'laydi.
 *
 * Nima uchun kerak: admin hamkasbiga "shu ekranga qara" deb havola
 * yuboradi, F5 bosadi, brauzer «orqaga» tugmasini bosadi. Holat faqat
 * React state'da yashasa, bularning uchtasi ham filtrni yo'qotadi va
 * odam qidiruvni qaytadan teradi.
 *
 * URL kaliti prefiks bilan yoziladi (`q`, `f.status`, `p`, `s`), shunda
 * bitta sahifada bir nechta jadval bo'lsa ham to'qnashmaydi.
 */
function useUrlState(namespace, enabled) {
  const [searchParams, setSearchParams] = useSearchParams()

  const prefix = namespace ? `${namespace}.` : ''
  const key = useCallback((name) => `${prefix}${name}`, [prefix])

  const read = useCallback(
    () => {
      if (!enabled) return null
      const filters = {}
      searchParams.forEach((value, rawKey) => {
        if (!rawKey.startsWith(`${prefix}f.`)) return
        filters[rawKey.slice(prefix.length + 2)] = value
      })
      const page = Number(searchParams.get(key('p')))
      const rawSort = searchParams.get(key('s'))
      return {
        search: searchParams.get(key('q')) || '',
        filters,
        page: Number.isFinite(page) && page > 0 ? page - 1 : 0,
        sort: rawSort
          ? [{
              field: rawSort.startsWith('-') ? rawSort.slice(1) : rawSort,
              sort: rawSort.startsWith('-') ? 'desc' : 'asc',
            }]
          : null,
      }
    },
    [enabled, searchParams, prefix, key],
  )

  const write = useCallback(
    ({ search, filters, page, sort }) => {
      if (!enabled) return
      setSearchParams(
        (previous) => {
          const next = new URLSearchParams(previous)
          // Avval shu jadvalga tegishli barcha kalitlarni tozalaymiz —
          // aks holda olib tashlangan filtr URL'da qolib ketadi.
          Array.from(next.keys())
            .filter((item) => item === key('q') || item === key('p') || item === key('s') || item.startsWith(`${prefix}f.`))
            .forEach((item) => next.delete(item))

          if (search) next.set(key('q'), search)
          Object.entries(filters || {}).forEach(([name, value]) => {
            if (value !== '' && value != null) next.set(`${prefix}f.${name}`, String(value))
          })
          if (page > 0) next.set(key('p'), String(page + 1))
          if (sort?.length) {
            next.set(key('s'), sort[0].sort === 'desc' ? `-${sort[0].field}` : sort[0].field)
          }
          return next
        },
        // `replace` — har bir harf brauzer tarixiga yozilmasin, aks holda
        // «orqaga» tugmasi qidiruvni harfma-harf orqaga qaytaradi.
        { replace: true },
      )
    },
    [enabled, setSearchParams, prefix, key],
  )

  return { read, write }
}

/**
 * Resurs (model) bilan ishlash uchun yagona hook.
 *
 * Tezlik qarorlari:
 *   - `keepPreviousData`: sahifa almashganda jadval bo'shamaydi;
 *   - keyingi sahifa oldindan yuklanadi (prefetch) — "Keyingi" bosilganda
 *     ma'lumot allaqachon keshda bo'ladi;
 *   - qidiruv 350 ms kechiktiriladi;
 *   - saralash va filtrlash serverga uzatiladi.
 *
 * Xavfsizlik qarorlari:
 *   - mutatsiyalar `retry: false` — yaratish/o'chirishni qayta urinish
 *     dublikat yoki kutilmagan o'chirishga olib kelishi mumkin;
 *   - o'zgarishdan keyin kesh invalidatsiya qilinadi (eskirgan ma'lumot
 *     ko'rsatilmaydi).
 */
export function useResource({
  key,
  api,
  pageSize = 25,
  defaultSort = null,
  defaultFilters = null,
  staticParams = {},
  searchable = true,
  /** URL'ga yozish. `false` — dialog ichidagi ko'makchi jadvallar uchun. */
  syncUrl = true,
  /** Bir sahifada bir nechta jadval bo'lsa — URL kalitlarini ajratadi. */
  urlNamespace = '',
  /**
   * Ro'yxatni O'ZI yangilash oralig'i (ms). `false` — yangilamaydi.
   *
   * Konfiguratsiya jadvallari uchun kerak emas (ularni odam
   * o'zgartiradi), lekin "hozir nima bo'lyapti" degan savolga javob
   * beradigan ro'yxatlar bor: qurilma onlayn holati 45 soniyada
   * o'zgaradi va operatordan sahifani qo'lda yangilashni kutish
   * mumkin emas.
   */
  refetchInterval = false,
}) {
  const queryClient = useQueryClient()
  const { notify, notifyError } = useUi()
  const url = useUrlState(urlNamespace, syncUrl)

  // Boshlang'ich holat URL'dan o'qiladi: havola bo'yicha kelgan odam
  // to'g'ri filtrlangan ekranni BIRINCHI renderda ko'radi, keyin
  // "sakrab" o'zgarmaydi.
  const initial = useRef(url.read()).current

  // «Sahifada» tanlovi HAR JADVAL uchun eslab qolinadi (brauzerda):
  // proktor sessiyalarni 100 tadan ko'radi, administrator kompyuterlarni
  // 25 tadan — va har safar sahifa ochilganda qaytadan tanlamasligi
  // kerak. URL'ga yozilmaydi: havola ulashilganda qabul qiluvchining
  // o'z tanlovi ustun bo'lishi kerak.
  const pageSizeKey = `proctoring.pageSize.${key}`
  const [paginationModel, setPaginationModel] = useState(() => {
    let remembered = null
    try {
      remembered = Number(localStorage.getItem(pageSizeKey)) || null
    } catch {
      remembered = null
    }
    return {
      page: initial?.page || 0,
      pageSize: [25, 50, 100].includes(remembered) ? remembered : pageSize,
    }
  })
  useEffect(() => {
    try {
      localStorage.setItem(pageSizeKey, String(paginationModel.pageSize))
    } catch {
      // Maxfiy rejim yoki to'lgan xotira — tanlov shu sahifada qoladi.
    }
  }, [pageSizeKey, paginationModel.pageSize])
  const [sortModel, setSortModel] = useState(
    initial?.sort || (defaultSort ? [defaultSort] : []),
  )
  const [search, setSearch] = useState(initial?.search || '')
  const [filters, setFilters] = useState(() => {
    const fromUrl = initial?.filters || {}
    return Object.keys(fromUrl).length ? fromUrl : { ...(defaultFilters || {}) }
  })
  const [serverError, setServerError] = useState(null)
  // Cursor sahifalash uchun: joriy kursor va "orqaga" tarixi.
  // Kursorli javobda `previous` har doim ham bo'lmaydi, shuning uchun
  // o'tilgan kursorlarni stack'da saqlaymiz.
  const [cursor, setCursor] = useState(null)
  const [cursorHistory, setCursorHistory] = useState([])

  const debouncedSearch = useDebounced(search)

  // `staticParams` odatda inline obyekt sifatida uzatiladi
  // (`staticParams={{ unresolved: 'true' }}`), ya'ni har renderda YANGI
  // havola. Uni to'g'ridan-to'g'ri dep massiviga qo'yish cheksiz
  // qayta-so'rovga olib keladi. Shuning uchun havola emas, MAZMUNI
  // kuzatiladi: qiymat o'zgarsagina query kaliti yangilanadi.
  const staticParamsKey = JSON.stringify(staticParams || {})
  const staticParamsRef = useRef(staticParams)
  staticParamsRef.current = staticParams

  // Qidiruv yoki filtr o'zgarsa — birinchi sahifaga qaytamiz. Aks holda
  // foydalanuvchi 5-sahifada turib qidirsa, bo'sh natija ko'radi.
  //
  // Birinchi renderni O'TKAZIB YUBORAMIZ: aks holda URL'dan o'qilgan
  // sahifa raqami darhol 0 ga tushib, havoladagi `?p=3` yo'qoladi.
  const isFirstRun = useRef(true)
  useEffect(() => {
    if (isFirstRun.current) {
      isFirstRun.current = false
      return
    }
    setPaginationModel((prev) => (prev.page === 0 ? prev : { ...prev, page: 0 }))
    setCursor(null)
    setCursorHistory([])
  }, [debouncedSearch, filters, sortModel, staticParamsKey])

  // Holatni URL'ga ko'chiramiz (kursorli rejimda sahifa raqami ma'nosiz —
  // kursor o'zi vaqtinchalik, uni havolada saqlash chalg'itadi).
  useEffect(() => {
    url.write({
      search: debouncedSearch,
      filters,
      page: cursor ? 0 : paginationModel.page,
      sort: sortModel,
    })
  }, [debouncedSearch, filters, paginationModel.page, sortModel, cursor]) // eslint-disable-line react-hooks/exhaustive-deps

  const buildParams = useCallback(
    (page, cursorValue) => {
      const params = {
        page_size: paginationModel.pageSize,
        ...staticParamsRef.current,
        ...Object.fromEntries(Object.entries(filters).filter(([, value]) => value !== '' && value != null)),
      }
      // Cursor va page bir vaqtda yuborilmaydi: DRF kursorli sahifalashda
      // `page` ni e'tiborsiz qoldiradi, lekin ikkalasini yuborish query
      // kalitini keraksiz o'zgartiradi va keshni buzadi.
      if (cursorValue) params.cursor = cursorValue
      else params.page = page + 1

      if (searchable && debouncedSearch.trim()) params.search = debouncedSearch.trim()
      if (sortModel.length > 0) {
        const { field, sort } = sortModel[0]
        params.ordering = sort === 'desc' ? `-${field}` : field
      }
      return params
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [paginationModel.pageSize, filters, debouncedSearch, sortModel, searchable, staticParamsKey],
  )

  const queryKey = useMemo(
    () => [key, buildParams(paginationModel.page, cursor)],
    [key, buildParams, paginationModel.page, cursor],
  )

  const query = useQuery({
    queryKey,
    queryFn: () => api.list(buildParams(paginationModel.page, cursor)),
    placeholderData: keepPreviousData,
    refetchInterval,
  })

  // Backend ikki xil sahifalashni ishlatadi:
  //   - konfiguratsiya jadvallari: `count` bilan (sahifa raqamlari);
  //   - sessiya/hodisa/audit: kursor bilan (milliardlab qatorda OFFSET
  //     ishlamaydi, shuning uchun `count` ataylab qaytarilmaydi).
  // Ikkalasini ham qo'llab-quvvatlaymiz.
  const isCursorMode = Boolean(query.data) && !('count' in query.data)
  const nextCursor = extractCursor(query.data?.next)
  const hasNext = isCursorMode ? Boolean(query.data?.next) : false
  const hasPrevious = isCursorMode ? cursorHistory.length > 0 : false

  const goNextPage = useCallback(() => {
    if (!nextCursor) return
    setCursorHistory((prev) => [...prev, cursor])
    setCursor(nextCursor)
  }, [nextCursor, cursor])

  const goPreviousPage = useCallback(() => {
    setCursorHistory((prev) => {
      if (prev.length === 0) return prev
      const copy = [...prev]
      setCursor(copy.pop() ?? null)
      return copy
    })
  }, [])

  // Keyingi sahifani oldindan yuklaymiz (ikkala rejim uchun ham).
  useEffect(() => {
    if (!query.data) return undefined

    if (isCursorMode) {
      if (!nextCursor) return undefined
      queryClient.prefetchQuery({
        queryKey: [key, buildParams(0, nextCursor)],
        queryFn: () => api.list(buildParams(0, nextCursor)),
        staleTime: 15_000,
      })
      return undefined
    }

    const total = query.data.count
    const loaded = (paginationModel.page + 1) * paginationModel.pageSize
    if (!total || loaded >= total) return undefined
    const nextPage = paginationModel.page + 1
    queryClient.prefetchQuery({
      queryKey: [key, buildParams(nextPage, null)],
      queryFn: () => api.list(buildParams(nextPage, null)),
      staleTime: 15_000,
    })
    return undefined
  }, [query.data, isCursorMode, nextCursor, paginationModel, key, api, buildParams, queryClient])

  /**
   * Mavjud bo'lmagan sahifadan birinchisiga qaytish.
   *
   * Sahifa raqami havolada saqlanadi, ya'ni `?p=7` linki bir hafta
   * yashashi mumkin — o'shancha vaqtda yozuvlar o'chib, 7-sahifa
   * yo'qolgan bo'ladi. DRF bunday holda 404 qaytaradi va ekranda
   * "qayta urinish" tugmasi qoladi: u har safar yana 404 beradi,
   * foydalanuvchi esa qamalib qoladi. Shuning uchun bunday xato
   * ushlanadi va ro'yxat birinchi sahifadan ochiladi.
   */
  useEffect(() => {
    if (query.error?.response?.status !== 404) return
    if (cursor) {
      setCursor(null)
      setCursorHistory([])
    } else if (paginationModel.page > 0) {
      setPaginationModel((prev) => ({ ...prev, page: 0 }))
    }
  }, [query.error, cursor, paginationModel.page])

  const invalidate = useCallback(
    () => queryClient.invalidateQueries({ queryKey: [key] }),
    [queryClient, key],
  )

  const createMutation = useMutation({
    mutationFn: (payload) => api.create(payload),
    retry: false,
    onSuccess: () => {
      setServerError(null)
      notify('Yozuv qo‘shildi')
      invalidate()
    },
    onError: (error) => setServerError(error),
  })

  const updateMutation = useMutation({
    mutationFn: (payload) => api.update(payload),
    retry: false,
    onSuccess: () => {
      setServerError(null)
      notify('O‘zgarishlar saqlandi')
      invalidate()
    },
    onError: (error) => setServerError(error),
  })

  const removeMutation = useMutation({
    mutationFn: (id) => api.remove(id),
    retry: false,
    onSuccess: () => {
      notify('Yozuv o‘chirildi')
      invalidate()
    },
    onError: notifyError,
  })

  /**
   * Bir maydonni tezkor almashtirish (masalan `is_active`).
   *
   * Optimistik: UI darhol o'zgaradi, xato bo'lsa avvalgi holat qaytariladi.
   * Ro'yxatdagi kalitni to'g'ridan-to'g'ri tahrirlash uchun qulay.
   */
  // Yumshoq o'chirilgan yozuvni tiklash. `api.restore` bo'lmagan
  // resurslarda bu mutatsiya hech qachon chaqirilmaydi (`ResourcePage`
  // tugmani ko'rsatmaydi).
  const restoreMutation = useMutation({
    mutationFn: (id) => api.restore(id),
    retry: false,
    onSuccess: () => {
      notify('Yozuv tiklandi')
      invalidate()
    },
  })

  const patchMutation = useMutation({
    mutationFn: ({ id, ...payload }) => api.update({ id, ...payload }),
    retry: false,
    onMutate: async ({ id, ...payload }) => {
      await queryClient.cancelQueries({ queryKey })
      const previous = queryClient.getQueryData(queryKey)
      queryClient.setQueryData(queryKey, (old) => {
        if (!old?.results) return old
        return {
          ...old,
          results: old.results.map((row) => (row.id === id ? { ...row, ...payload } : row)),
        }
      })
      return { previous }
    },
    onError: (error, _variables, context) => {
      if (context?.previous) queryClient.setQueryData(queryKey, context.previous)
      notifyError(error)
    },
    onSettled: invalidate,
  })

  return {
    // Ma'lumot
    rows: query.data?.results || [],
    // Kursorli rejimda umumiy son yo'q — `undefined` qaytaramiz, shunda
    // DataTable server sahifalashni yoqmaydi va bo'sh jadval chizmaydi.
    total: isCursorMode ? undefined : (query.data?.count ?? 0),
    isCursorMode,
    hasNext,
    hasPrevious,
    goNextPage,
    goPreviousPage,
    /**
     * Kursorli rejimda o'tib kelingan sahifalar soni.
     *
     * Tartib raqamini uzluksiz chiqarish uchun kerak. Kursorli
     * sahifalashda umumiy son so'ralmaydi, lekin oldingi sahifalar
     * DOIM to'liq bo'ladi (oxirgisidan boshqasi) — demak siljish
     * `sahifalar soni x sahifa hajmi` ga teng.
     */
    cursorPageIndex: cursorHistory.length,
    isLoading: query.isLoading,
    isFetching: query.isFetching,
    error: query.error,
    refetch: query.refetch,

    /**
     * Joriy ro'yxatni TORAYTIRADIGAN parametrlar (filtr, qidiruv,
     * `staticParams`) — sahifa va tartibsiz. Ommaviy amalning "filtrga
     * mos hammasi" rejimi serverga aynan shularni yuboradi
     * (`BulkSelectionMixin`), ya'ni ekrandagi ro'yxat bilan bir xil to'plam.
     */
    scopeParams: (() => {
      const { page, page_size: pageSizeParam, cursor: cursorParam, ordering, ...rest } =
        buildParams(0, null)
      return rest
    })(),

    // Jadval holati
    paginationModel,
    setPaginationModel,
    sortModel,
    setSortModel,
    search,
    setSearch,
    filters,
    setFilters,
    setFilter: useCallback(
      (name, value) => setFilters((prev) => ({ ...prev, [name]: value })),
      [],
    ),
    resetFilters: useCallback(() => {
      setFilters({ ...(defaultFilters || {}) })
      setSearch('')
    }, [defaultFilters]),

    /** Joriy so'rov parametrlari — eksport va "havolani nusxalash" uchun. */
    currentParams: buildParams(paginationModel.page, cursor),

    // Mutatsiyalar
    create: createMutation.mutate,
    update: updateMutation.mutate,
    remove: removeMutation.mutate,
    restore: restoreMutation.mutate,
    isRestoring: restoreMutation.isPending,
    patch: patchMutation.mutate,
    isSaving: createMutation.isPending || updateMutation.isPending,
    isDeleting: removeMutation.isPending,
    isPatching: patchMutation.isPending,
    serverError,
    clearServerError: useCallback(() => setServerError(null), []),
    invalidate,
  }
}

/** DRF qaytargan to'liq `next` URL'idan `cursor` parametrini ajratadi. */
function extractCursor(url) {
  if (!url) return null
  try {
    return new URL(url, window.location.origin).searchParams.get('cursor')
  } catch {
    return null
  }
}

/**
 * Select maydonlari uchun variantlar (uzoq keshlanadi — kam o'zgaradi).
 *
 * MUHIM: bitta so'rov bilan cheklanmaydi. Ilgari bu yerda `page_size: 300`
 * turardi va 300 dan ortiq bino bo'lgan tizimda ortiqchasi JIMGINA tushib
 * qolardi — forma to'g'ri ko'rinardi, lekin kerakli bino ro'yxatda yo'q
 * edi. Endi barcha sahifalar ketma-ket olinadi va `truncated` bayrog'i
 * chegaraga yetilganini ochiq aytadi.
 */
const OPTIONS_HARD_LIMIT = 5000

export function useOptions(key, api, mapper, params = {}) {
  const query = useQuery({
    queryKey: [key, 'options', params],
    queryFn: () => fetchAllPages(api, params),
    staleTime: 5 * 60 * 1000,
    gcTime: 10 * 60 * 1000,
  })

  return {
    options: useMemo(() => (query.data?.items || []).map(mapper), [query.data, mapper]),
    isLoading: query.isLoading,
    truncated: Boolean(query.data?.truncated),
  }
}

/**
 * Barcha sahifalarni yig'ib `{ results }` qaytaradi — `list()` javobi
 * shaklida, ya'ni `results` ga tayangan mavjud kod o'zgarmaydi.
 * Filtr variantlari uchun (jonli kuzatuv): bitta `page_size: 200`
 * so'rovi 200 dan ortiq binoni jimgina kesib tashlardi.
 */
export async function listAll(api, params = {}) {
  const { items } = await fetchAllPages(api, params)
  return { results: items }
}

async function fetchAllPages(api, params) {
  const pageSize = params.page_size || 200
  const items = []
  let page = 1

  for (;;) {
    // eslint-disable-next-line no-await-in-loop
    const data = await api.list({ ...params, page_size: pageSize, page })
    // `pagination_class = None` bo'lgan endpointlar (masalan `/permissions/`)
    // to'g'ridan-to'g'ri massiv qaytaradi — o'ram yo'q.
    const chunk = Array.isArray(data) ? data : (data?.results || [])
    items.push(...chunk)

    const done =
      Array.isArray(data) ||
      chunk.length < pageSize ||
      !data?.next ||
      items.length >= OPTIONS_HARD_LIMIT
    if (done) return { items, truncated: items.length >= OPTIONS_HARD_LIMIT }
    page += 1
  }
}
