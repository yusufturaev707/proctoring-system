import { EVENT_LABEL } from './labels'

/**
 * Hodisalar tasnifi.
 *
 * NIMA UCHUN KERAK: hodisa oqimi tekis ro'yxat bo'lganda u ishlamaydi.
 * Talabgor oynadan bir necha marta chiqsa, o'nlab `window_blur` yozuvi
 * yog'iladi va ular orasidagi bitta `rdp_detected` ni proktor
 * ko'rmaydi — holbuki birinchisi "chalg'idi", ikkinchisi "mashinani
 * boshqa odam boshqaryapti" degani.
 *
 * Shuning uchun turlar MA'NOSI bo'yicha guruhlanadi:
 *
 *   integrity — mashinaga ishonib bo'lmaydi. Bu texnik holat va u
 *               talabgorning xulqidan mustaqil: masofaviy boshqaruv,
 *               virtual mashina, ikkinchi monitor, soxta kadr.
 *               Proktor bularni HAMMASIDAN oldin ko'rishi kerak.
 *   identity  — bu o'sha odammi. Yuz tekshiruvi natijalari.
 *   behaviour — talabgor nima qilyapti. Ular ko'p va takrorlanadi;
 *               bittasining o'zi qaror uchun asos emas, tendentsiya esa
 *               asos bo'ladi.
 *   system    — fon holati. Ular xavf emas, lekin ULARSIZ boshqa
 *               hodisalardagi bo'shliqni tushuntirib bo'lmaydi
 *               (tarmoq uzilgan payt).
 *
 * Guruh nomlari backendda YO'Q va bo'lishi ham shart emas: bu sof
 * taqdimot qarori. Backend jiddiylikni (`severity`) beradi, u esa
 * boshqa savolga javob beradi — "qanchalik jiddiy", "qaysi turkumdan"
 * emas.
 */

export const EVENT_CATEGORY = {
  // --- Qurilma butunligi ---
  rdp_detected: 'integrity',
  vm_detected: 'integrity',
  process_blacklisted: 'integrity',
  client_anomaly: 'integrity',
  multi_monitor: 'integrity',
  camera_lost: 'integrity',
  camera_blocked: 'integrity',

  // --- Shaxs ---
  face_mismatch: 'identity',
  multiple_faces: 'identity',
  face_not_found: 'identity',

  // --- Xulq ---
  window_blur: 'behaviour',
  fullscreen_exit: 'behaviour',
  hotkey_blocked: 'behaviour',
  clipboard_blocked: 'behaviour',
  navigation_blocked: 'behaviour',
  object_detected: 'behaviour',

  // --- Tizim / fon ---
  window_focus: 'system',
  network_lost: 'system',
  network_restored: 'system',
  proctor_warning: 'system',
  session_terminated: 'system',
}

/**
 * Guruh metama'lumoti.
 *
 * `color` — MUI palitrasidagi nom; u ham nishonda, ham qatorning chap
 * chekkasidagi chiziqda ishlatiladi. Rang YAGONA belgi emas: har bir
 * qatorda yorliq matni ham bor, shuning uchun rang ko'rmaydigan
 * foydalanuvchi hech narsa yo'qotmaydi.
 */
export const CATEGORY_META = {
  integrity: { label: 'Qurilma', full: 'Qurilma butunligi', color: 'error', order: 0 },
  identity: { label: 'Shaxs', full: 'Shaxsni tekshirish', color: 'warning', order: 1 },
  behaviour: { label: 'Xulq', full: 'Talabgor xulqi', color: 'info', order: 2 },
  system: { label: 'Tizim', full: 'Tizim holati', color: 'default', order: 3 },
}

export const CATEGORY_ORDER = Object.keys(CATEGORY_META).sort(
  (a, b) => CATEGORY_META[a].order - CATEGORY_META[b].order,
)

/** Noma'lum tur (yangi server, eski panel) — "tizim" deb qaraladi. */
export const categoryOf = (eventType) => EVENT_CATEGORY[eventType] || 'system'

export const isIntegrityEvent = (eventType) => categoryOf(eventType) === 'integrity'

export const eventLabel = (eventType) => EVENT_LABEL[eventType] || eventType

/**
 * Backend yuborgan `detail` ni bitta qatorga aylantiradi.
 *
 * Backend oq ro'yxat bo'yicha ixcham obyekt beradi
 * (`ingest._BROADCAST_DETAIL_KEYS`), bu yerda esa u o'qiladigan matnga
 * aylanadi. Tarjima FRONTENDDA: matn tili va shakli taqdimot qarori,
 * uni serverga ko'chirish ikkalasini bir-biriga bog'lab qo'yardi.
 *
 * Noma'lum kalitlar JIMGINA tashlanadi — yangi server eski panelni
 * buzmasligi kerak.
 */
export function eventDetail(eventType, detail) {
  if (!detail || typeof detail !== 'object') return ''
  const parts = []

  if (Array.isArray(detail.processes) && detail.processes.length) {
    parts.push(detail.processes.join(', '))
  }
  if (typeof detail.count === 'number') {
    parts.push(`${detail.count} ta ekran`)
  }
  if (detail.key) {
    parts.push(
      detail.repeats > 1 ? `${detail.key} (${detail.repeats} marta)` : String(detail.key),
    )
  }
  if (detail.kind) parts.push(ANOMALY_KIND[detail.kind] || String(detail.kind))
  if (detail.reason) parts.push(ANOMALY_KIND[detail.reason] || String(detail.reason))
  if (detail.host) parts.push(String(detail.host))

  // Yuz tekshiruvida ball chegara bilan birga ma'noga ega: "42" o'z-o'zicha
  // hech nima demaydi, "42 / 70" esa qanchalik uzoq ekanini ko'rsatadi.
  if (typeof detail.score === 'number') {
    parts.push(
      typeof detail.threshold === 'number'
        ? `ball ${detail.score}/${detail.threshold}`
        : `ball ${detail.score}`,
    )
  }
  if (typeof detail.faces === 'number' && detail.faces !== 1) {
    parts.push(`${detail.faces} ta yuz`)
  }

  return parts.join(' • ')
}

/** Client yuboradigan sabab kodlari — o'qiladigan matnga. */
const ANOMALY_KIND = {
  identical_frames: 'bir xil kadrlar',
  app_hash_changed: 'dastur fayli o‘zgargan',
  fingerprint_changed: 'apparat izi o‘zgargan',
  fingerprint_shared: 'bir apparatda bir necha qurilma',
  download: 'yuklab olishga urinish',
}

/**
 * Ketma-ket takrorlangan hodisalarni bitta qatorga yig'adi.
 *
 * Bir sessiyada Alt+Tab yigirma marta bosilsa, oqimda yigirmata bir xil
 * qator paydo bo'ladi va ular boshqa hamma narsani surib chiqaradi.
 * Yig'ilgandan keyin ular bitta qator va "×20" bo'ladi — ma'lumot
 * YO'QOLMAYDI, aksincha takror sonining o'zi signalga aylanadi.
 *
 * Faqat KETMA-KET va bir xil (sessiya + tur) yozuvlar birlashtiriladi:
 * orada boshqa hodisa bo'lsa, u vaqt tartibini buzmasligi kerak.
 *
 * Ro'yxat eng yangisidan boshlanadi (`useLiveMonitor` yangi hodisani
 * boshiga qo'yadi), shuning uchun guruhning BIRINCHI elementi — eng
 * so'nggi takror. `occurred_at` o'shaniki bo'lib qoladi, eng eskisi
 * esa `first_at` da: proktor "qachon boshlandi va hali davom
 * etyaptimi" degan savolga shu ikkisidan javob oladi.
 */
export function collapseRepeats(events) {
  const result = []
  events.forEach((event) => {
    const previous = result[result.length - 1]
    if (
      previous &&
      previous.session_id === event.session_id &&
      previous.event_type === event.event_type
    ) {
      previous.repeats += 1
      previous.first_at = event.occurred_at
      return
    }
    result.push({ ...event, repeats: 1, first_at: event.occurred_at })
  })
  return result
}

/** Guruhlar bo'yicha sanoq (filtr nishonlarida ko'rsatiladi). */
export function countByCategory(events) {
  const counts = { integrity: 0, identity: 0, behaviour: 0, system: 0 }
  events.forEach((event) => {
    counts[categoryOf(event.event_type)] += 1
  })
  return counts
}
