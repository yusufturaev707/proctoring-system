/**
 * Kutubxona turlarini kengaytirish.
 *
 * `api/client.ts` interceptor'i so'rov konfiguratsiyasiga `_retried`
 * bayrog'ini qo'yadi (401 dan keyin refresh bir marta), React Query esa
 * xatolarni shu interceptor'dan o'tgan axios xatosi sifatida beradi —
 * `error.userMessage` / `error.response.status` ga har joyda qo'lda
 * tur keltirish yozmaslik uchun standart xato turi ro'yxatdan o'tadi.
 */
import 'axios'
import '@tanstack/react-query'
import type { ApiError } from './api'

declare module 'axios' {
  interface InternalAxiosRequestConfig {
    _retried?: boolean
  }
}

declare module '@tanstack/react-query' {
  interface Register {
    defaultError: ApiError
  }
}
