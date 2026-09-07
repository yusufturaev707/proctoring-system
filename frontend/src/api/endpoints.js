import api from './client'

/** Barcha backend chaqiruvlari shu yerda — komponentlarda URL yozilmaydi. */

const list = (url) => (params) => api.get(url, { params }).then((r) => r.data)
const detail = (url) => (id) => api.get(`${url}${id}/`).then((r) => r.data)
const create = (url) => (payload) => api.post(url, payload).then((r) => r.data)
const update = (url) => ({ id, ...payload }) => api.patch(`${url}${id}/`, payload).then((r) => r.data)
const remove = (url) => (id) => api.delete(`${url}${id}/`).then((r) => r.data)
// Yumshoq o'chirilgan yozuvni qaytaradi. Faqat `SoftDeleteRestoreMixin`
// ulangan endpointlarda mavjud — boshqasida server 404 beradi, shuning
// uchun `ResourcePage` uni faqat `restorable` bo'lganda ko'rsatadi.
const restore = (url) => (id) => api.post(`${url}${id}/restore/`).then((r) => r.data)

const crud = (url) => ({
  list: list(url),
  detail: detail(url),
  create: create(url),
  update: update(url),
  remove: remove(url),
  restore: restore(url),
})

export const auth = {
  login: (payload) => api.post('/auth/login/', payload).then((r) => r.data),
  logout: (refresh) => api.post('/auth/logout/', { refresh }).then((r) => r.data),
  me: () => api.get('/auth/me/').then((r) => r.data),
}

export const dashboard = {
  summary: (params) => api.get('/dashboard/summary/', { params }).then((r) => r.data),
  zones: (params) => api.get('/dashboard/zones/', { params }).then((r) => r.data),
  devices: () => api.get('/dashboard/devices/').then((r) => r.data),
}

export const sessions = {
  ...crud('/sessions/'),
  live: (params) => api.get('/sessions/live/', { params }).then((r) => r.data),
  events: (id, params) => api.get(`/sessions/${id}/events/`, { params }).then((r) => r.data),
  faceLogs: (id, params) => api.get(`/sessions/${id}/face-logs/`, { params }).then((r) => r.data),
  screenshots: (id, params) => api.get(`/sessions/${id}/screenshots/`, { params }).then((r) => r.data),
  storedScreenshots: (id, params) =>
    api.get(`/sessions/${id}/stored-screenshots/`, { params }).then((r) => r.data),
  warn: (id, payload) => api.post(`/sessions/${id}/warn/`, payload).then((r) => r.data),
  terminate: (id, payload) => api.post(`/sessions/${id}/terminate/`, payload).then((r) => r.data),
}

/**
 * Skrinshot faylini blob sifatida oladi.
 *
 * `<img src={url}>` ishlamaydi: brauzer rasm so'roviga `Authorization`
 * sarlavhasini qo'shmaydi, ya'ni endpoint 401 beradi. Tokenni URL'ga
 * qo'yish esa uni brauzer tarixiga, `Referer` ga va nginx access log'iga
 * chiqaradi — bu sessiya tokeni uchun qabul qilib bo'lmaydi.
 *
 * Shuning uchun rasm axios orqali olinadi va `URL.createObjectURL` bilan
 * `<img>` ga beriladi. Baytlarni baribir nginx uzatadi (Django faqat
 * `X-Accel-Redirect` qaytaradi) — bu yerda o'zgaradigan narsa faqat
 * autentifikatsiya.
 *
 * MUHIM: chaqiruvchi ishi tugagach `URL.revokeObjectURL(url)` qilishi
 * SHART, aks holda galereyani varaqlash brauzer xotirasini to'ldiradi.
 */
export const screenshotFile = {
  objectUrl: async (id) => {
    const response = await api.get(`/screenshots/${id}/file/`, { responseType: 'blob' })
    return URL.createObjectURL(response.data)
  },
}

export const technicalProblems = {
  ...crud('/technical-problems/'),
  resolve: (id, payload) => api.post(`/technical-problems/${id}/resolve/`, payload).then((r) => r.data),
}

export const users = {
  ...crud('/users/'),
  setPassword: (id, password) => api.post(`/users/${id}/set-password/`, { password }).then((r) => r.data),
}

export const roles = crud('/roles/')
export const permissions = { list: list('/permissions/') }
export const regions = crud('/regions/')
export const zones = crud('/zones/')
export const computers = crud('/computers/')
export const cameras = crud('/cameras/')
export const examTypes = crud('/exam-types/')
export const exams = crud('/exams/')
export const examSchedules = crud('/exam-schedules/')
export const auditLogs = { list: list('/audit-logs/') }

export const deviceTokens = {
  ...crud('/device-tokens/'),
  approve: (id) => api.post(`/device-tokens/${id}/approve/`).then((r) => r.data),
  revoke: (id, reason) => api.post(`/device-tokens/${id}/revoke/`, { reason }).then((r) => r.data),
}

export const settings = {
  ...crud('/settings/'),
  // `examId` berilsa — o'sha imtihonning profili, aks holda global standart.
  clientConfig: (examId) =>
    api.get('/settings/client-config/', { params: examId ? { exam: examId } : undefined })
      .then((r) => r.data),
  activate: (id) => api.post(`/settings/${id}/activate/`).then((r) => r.data),
}

export const allowedIps = crud('/allowed-ips/')
export const exitPasswords = crud('/exit-passwords/')
export const cocoGroups = crud('/coco-groups/')
export const cocoObjects = crud('/coco-objects/')
export const rdpObjects = crud('/rdp-objects/')
export const hotkeys = crud('/hotkeys/')
export const modelVersions = crud('/model-versions/')
