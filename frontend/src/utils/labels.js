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
  peripheral_connected: 'Qo‘shimcha qurilma ulandi',
  peripheral_removed: 'Qo‘shimcha qurilma uzildi',
  face_not_found: 'Yuz topilmadi',
  face_mismatch: 'Yuz mos kelmadi',
  multiple_faces: 'Bir nechta yuz',
  object_detected: 'Taqiqlangan obyekt',
  // --- AI kuzatuv: shaxs ---
  face_occluded: 'Yuz qisman yopilgan',
  face_too_far: 'Yuz juda uzoqda',
  face_too_close: 'Yuz juda yaqin',
  student_left_frame: 'Kadrdan chiqdi',
  second_person: 'Kadrda ikkinchi odam',
  // --- AI kuzatuv: nigoh va poza ---
  looking_away: 'Chetga qaradi',
  prolonged_looking_away: 'Uzoq vaqt chetga qaradi',
  excessive_head_movement: 'Bosh harakati ko‘p',
  eyes_closed: 'Ko‘zlar yumuq',
  hand_below_desk: 'Qo‘l stol ostida',
  suspicious_hand_movement: 'Shubhali qo‘l harakati',
  unauthorized_device: 'Ruxsatsiz qurilma',
  // --- AI kuzatuv: birlashtirilgan xulosa ---
  high_suspicion_phone: 'Yuqori shubha — telefon',
  high_suspicion_person: 'Yuqori shubha — begona shaxs',
  high_suspicion_identity: 'Yuqori shubha — shaxs almashtirilgan',
  // --- AI kuzatuvning o'z holati ---
  camera_degraded: 'Kamera sifati pasaydi',
  camera_reconnected: 'Kamera qayta ulandi',
  proctoring_degraded: 'Kuzatuv cheklangan rejimda',
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

// Client apparatga qarab o'zi tanlaydigan unumdorlik profili.
// Ro'yxat `controls.ProctoringPolicy.GpuProfile` bilan bir xil
// (`auto` dan tashqari - u administrator TANLOVI, client esa
// O'LCHOV natijasini yuboradi).
export const AI_PROFILE_LABEL = {
  high: 'Yuqori (GPU)',
  medium: 'O‘rta (GPU)',
  low: 'Past',
  cpu: 'Faqat CPU',
  minimal: 'Minimal (faqat yuz)',
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

/**
 * Kompyuterning ekrandagi nomi: "№12 · INV-001".
 *
 * BITTA JOYDA, chunki u beshta ekranda ko'rinadi (sessiyalar,
 * jonli kuzatuv, sessiya tafsiloti, qurilma tokenlari, kompyuterlar)
 * va har birida alohida yozilsa, ular albatta ajralib ketardi -
 * biri raqamsiz mashinada "№null" chiqarardi, ikkinchisi bo'sh
 * katak.
 *
 * RAQAM OLDINDA: operator mashinani aynan shu bo'yicha qidiradi,
 * inventar kodi esa buxgalteriya uchun va stikerning orqasida.
 */
export const computerLabel = (number, code) => {
  if (number) return code ? `№${number} · ${code}` : `№${number}`
  return code || ''
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
