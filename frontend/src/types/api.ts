import type { AxiosError } from 'axios'

/**
 * Server qaytaradigan yozuv.
 *
 * ATAYLAB keng (`any` qiymatli): panel 30 dan ortiq resursni bitta CRUD
 * dvigatelida (`ResourcePage`) chizadi va har resursning maydonlari
 * backend serializer'ida aniqlanadi. Har birini frontendda qo'lda
 * takrorlash serializer bilan ajralib ketadigan ikkinchi manba bo'lardi —
 * xato kompilyatsiyada emas, baribir ishlash paytida chiqardi. Aniq tur
 * kerak bo'lgan markaziy shakllar (joriy foydalanuvchi, sahifalash,
 * xato) quyida alohida yozilgan.
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type ApiRecord = Record<string, any>

/** So'rov parametrlari (`?page=…&search=…`). */
export type QueryParams = Record<string, unknown>

/** Yozuv identifikatori — URL'da satr, JSON'da son bo'lishi mumkin. */
export type Id = number | string

/**
 * Sahifalangan ro'yxat. Konfiguratsiya jadvallari `count` qaytaradi,
 * kursorli ro'yxatlar (sessiya, hodisa, audit) — yo'q.
 */
export interface Page<T = ApiRecord> {
  count?: number
  next?: string | null
  previous?: string | null
  results: T[]
}

/** CRUD dvigateli kutadigan API (`api/endpoints.ts:crud`). */
export interface CrudApi {
  list: (params?: QueryParams) => Promise<ApiRecord>
  detail?: (id: Id) => Promise<ApiRecord>
  create: (payload: ApiRecord) => Promise<ApiRecord>
  update: (payload: ApiRecord) => Promise<ApiRecord>
  remove: (id: Id) => Promise<unknown>
  restore?: (id: Id) => Promise<ApiRecord>
}

/** Faqat o'qiladigan ro'yxat (`audit-logs`, `permissions`). */
export interface ListApi {
  list: (params?: QueryParams) => Promise<ApiRecord>
}

/**
 * Axios xatosi + `api/client.ts` interceptor'i qo'shgan maydonlar.
 *
 * `userMessage` — foydalanuvchiga ko'rsatiladigan matn, `fieldErrors` —
 * serializer xatolari (`error.details`), forma maydonlariga yoyiladi.
 */
export type ApiError = AxiosError<ApiRecord> & {
  userMessage?: string
  fieldErrors?: ApiRecord | null
}

/** Joriy xodim (`auth/me/`). */
export interface CurrentUser extends ApiRecord {
  id: number
  username: string
  full_name?: string
  is_superuser?: boolean
  has_panel_access?: boolean
  is_region_scoped?: boolean
  lacks_region?: boolean
  permissions?: string[]
  region?: number | null
  region_name?: string | null
}
