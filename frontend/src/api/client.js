import axios from 'axios'

const BASE_URL = import.meta.env.VITE_API_URL || ''

export const TOKEN_KEY = 'proctoring.access'
export const REFRESH_KEY = 'proctoring.refresh'

export const tokens = {
  access: () => localStorage.getItem(TOKEN_KEY),
  refresh: () => localStorage.getItem(REFRESH_KEY),
  set: (access, refresh) => {
    localStorage.setItem(TOKEN_KEY, access)
    if (refresh) localStorage.setItem(REFRESH_KEY, refresh)
  },
  clear: () => {
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(REFRESH_KEY)
  },
}

const api = axios.create({
  baseURL: `${BASE_URL}/api/v1`,
  timeout: 20000,
  headers: { 'Content-Type': 'application/json' },
})

api.interceptors.request.use((config) => {
  const token = tokens.access()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

/**
 * Backend barcha javoblarni `{success, data, error}` konvertiga o'raydi.
 * Bu yerda uni ochamiz, shunda komponentlar `response.data.data` yozmaydi.
 */
api.interceptors.response.use(
  (response) => {
    if (response.data && typeof response.data === 'object' && 'success' in response.data) {
      response.data = response.data.data
    }
    return response
  },
  async (error) => {
    const { response, config } = error

    // 401 -> bir marta refresh qilib ko'ramiz.
    // `_retried` bayrog'i cheksiz siklning oldini oladi.
    if (response?.status === 401 && !config?._retried && tokens.refresh()) {
      config._retried = true
      try {
        const { data } = await axios.post(`${BASE_URL}/api/v1/auth/refresh/`, {
          refresh: tokens.refresh(),
        })
        const payload = data?.data || data
        tokens.set(payload.access, payload.refresh)
        config.headers.Authorization = `Bearer ${payload.access}`
        return api(config)
      } catch {
        tokens.clear()
        if (window.location.pathname !== '/login') window.location.href = '/login'
      }
    }

    // Backend xatosini o'qiladigan xabarga aylantiramiz.
    const apiError = response?.data?.error
    error.userMessage =
      apiError?.message ||
      (response?.status === 403
        ? 'Ushbu amal uchun ruxsatingiz yo‘q'
        : response?.status === 429
          ? 'Juda ko‘p so‘rov yuborildi, biroz kuting'
          : response
            ? `Xatolik (${response.status})`
            : 'Serverga ulanib bo‘lmadi')
    error.fieldErrors = apiError?.details || null
    return Promise.reject(error)
  },
)

export default api
