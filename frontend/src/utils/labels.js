import dayjs from 'dayjs'
import 'dayjs/locale/uz-latn'
import relativeTime from 'dayjs/plugin/relativeTime'

dayjs.extend(relativeTime)
dayjs.locale('uz-latn')

export const EVENT_LABEL = {
  window_blur: 'Oynadan chiqish',
  window_focus: 'Oynaga qaytish',
  fullscreen_exit: 'To‘liq ekrandan chiqish',
  hotkey_blocked: 'Tezkor tugma bloklandi',
  clipboard_blocked: 'Nusxa ko‘chirish bloklandi',
  multi_monitor: 'Bir nechta monitor',
  camera_lost: 'Kamera yo‘qoldi',
  camera_blocked: 'Kamera yopilgan',
  rdp_detected: 'Masofaviy boshqaruv',
  vm_detected: 'Virtual mashina',
  process_blacklisted: 'Taqiqlangan dastur',
  face_not_found: 'Yuz topilmadi',
  face_mismatch: 'Yuz mos kelmadi',
  multiple_faces: 'Bir nechta yuz',
  object_detected: 'Taqiqlangan obyekt',
  network_lost: 'Tarmoq uzildi',
  network_restored: 'Tarmoq tiklandi',
  client_anomaly: 'Client anomaliyasi',
  navigation_blocked: 'URL bloklandi',
  proctor_warning: 'Proktor ogohlantirdi',
  session_terminated: 'Sessiya tugatildi',
}

export const TP_KIND_LABEL = {
  power: 'Elektr',
  network: 'Tarmoq',
  hardware: 'Uskuna',
  software: 'Dastur',
  other: 'Boshqa',
}

export const DEVICE_STATUS_LABEL = {
  pending: 'Tasdiqlanmagan',
  active: 'Faol',
  revoked: 'Bekor qilingan',
}

export const COMPUTER_STATUS_LABEL = {
  offline: 'Offline',
  online: 'Online',
  in_exam: 'Imtihonda',
  blocked: 'Bloklangan',
}

export const AUDIT_ACTION_LABEL = {
  login: 'Kirish',
  logout: 'Chiqish',
  create: 'Yaratish',
  update: 'O‘zgartirish',
  delete: 'O‘chirish',
  session_warn: 'Ogohlantirish',
  session_terminate: 'Chetlashtirish',
  session_restore: 'Tiklash',
  tp_resolve: 'Texnik muammo qarori',
  setting_change: 'Sozlama o‘zgarishi',
  device_revoke: 'Qurilma bloklandi',
  export: 'Eksport',
}

export const formatDateTime = (value) => (value ? dayjs(value).format('DD.MM.YYYY HH:mm:ss') : '—')
export const formatDate = (value) => (value ? dayjs(value).format('DD.MM.YYYY') : '—')
export const formatTime = (value) => (value ? dayjs(value).format('HH:mm:ss') : '—')
export const fromNow = (value) => (value ? dayjs(value).fromNow() : '—')

/** Soniyani "1s 24d" ko'rinishiga aylantiradi. */
export const formatDuration = (seconds) => {
  if (seconds == null) return '—'
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  if (hours) return `${hours}s ${minutes}d`
  if (minutes) return `${minutes}d`
  return `${seconds}s`
}

export const formatBytes = (bytes) => {
  if (!bytes) return '—'
  const units = ['B', 'KB', 'MB', 'GB']
  let value = bytes
  let index = 0
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024
    index += 1
  }
  return `${value.toFixed(index === 0 ? 0 : 1)} ${units[index]}`
}
