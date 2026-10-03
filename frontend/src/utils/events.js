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
  // Fleshka, telefon, naushnik... - mashinaga tashqaridan nima kirdi.
  // Uzilish ham shu turkumda: "qachon olib qo'yildi" ulanish bilan
  // bir juft bo'lib o'qiladi.
  peripheral_connected: 'integrity',
  peripheral_removed: 'integrity',
  camera_lost: 'integrity',
  camera_blocked: 'integrity',
  // Kuzatuvning O'Z nosozligi ham butunlik masalasi: u "hech narsa
  // bo'lmadi" emas, "hech narsa KO'RILMADI" degani va proktor buni
  // xulq hodisalaridan oldin bilishi kerak.
  camera_degraded: 'integrity',
  proctoring_degraded: 'integrity',

  // --- Shaxs ---
  face_mismatch: 'identity',
  multiple_faces: 'identity',
  face_not_found: 'identity',
  face_occluded: 'identity',
  face_too_far: 'identity',
  face_too_close: 'identity',
  student_left_frame: 'identity',
  second_person: 'identity',
  high_suspicion_person: 'identity',
  high_suspicion_identity: 'identity',

  // --- Xulq ---
  window_blur: 'behaviour',
  fullscreen_exit: 'behaviour',
  hotkey_blocked: 'behaviour',
  clipboard_blocked: 'behaviour',
  navigation_blocked: 'behaviour',
  object_detected: 'behaviour',
  looking_away: 'behaviour',
  prolonged_looking_away: 'behaviour',
  excessive_head_movement: 'behaviour',
  eyes_closed: 'behaviour',
  hand_below_desk: 'behaviour',
  suspicious_hand_movement: 'behaviour',
  unauthorized_device: 'behaviour',
  high_suspicion_phone: 'behaviour',

  // --- Tizim / fon ---
  window_focus: 'system',
  // Tiklanish — fon holati: u xavf emas, lekin usiz "kamera
  // yo'qoldi" hodisasi abadiy ochiq bo'lib ko'rinardi.
  camera_reconnected: 'system',
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

/** `detail.count` birligi — hodisa turiga qarab. */
const COUNT_UNIT = {
  multi_monitor: 'ekran',
  second_person: 'odam',
}

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
    // `count` ikki xil hodisada keladi va birligi turga bog'liq:
    // `multi_monitor` — ekranlar, `second_person` — kadrdagi odamlar
    // (talabgor bilan). Ilgari hammasi "ta ekran" edi va «Kadrda
    // ikkinchi odam» ostida "2 ta ekran" chiqardi.
    const unit = COUNT_UNIT[eventType]
    parts.push(unit ? `${detail.count} ta ${unit}` : `${detail.count} ta`)
  }
  if (detail.key) {
    parts.push(
      detail.repeats > 1 ? `${detail.key} (${detail.repeats} marta)` : String(detail.key),
    )
  }
  if (detail.at_start === true) parts.push('imtihon boshida ulangan')
  if (detail.kind) {
    parts.push(ANOMALY_KIND[detail.kind] || PERIPHERAL_KIND[detail.kind] || String(detail.kind))
  }
  if (detail.reason) parts.push(ANOMALY_KIND[detail.reason] || String(detail.reason))
  if (detail.host) parts.push(String(detail.host))

  // --- Masofaviy boshqaruv / virtualizatsiya tozalash ---
  //
  // `neutralized` BIRINCHI o'rinda va bu ataylab: proktor uchun
  // "AnyDesk topildi va yopildi" bilan "AnyDesk topildi, yopib
  // bo'lmadi" butunlay boshqa vaziyat. Birinchisi bayonnomaga
  // yozuv, ikkinchisi esa darhol aralashuvni talab qiladi — ekran
  // hozir ham boshqa odamga ochiq bo'lishi mumkin. Ro'yxatning
  // oxiriga qo'yilsa, u uzun satrda ko'zdan qochardi.
  if (typeof detail.neutralized === 'boolean') {
    parts.unshift(detail.neutralized ? 'yopildi' : 'YOPIB BO‘LMADI')
  }
  if (detail.label) parts.push(String(detail.label))
  if (Array.isArray(detail.drives) && detail.drives.length) parts.push(detail.drives.join(', '))
  if (detail.service) parts.push(`xizmat: ${detail.service}`)
  if (detail.process) parts.push(String(detail.process))
  // Dalil — "nega shu dastur deb qaror qilindi". Apellyatsiyada
  // "AnyDesk edi" degan da'voni faqat shu satr tasdiqlaydi.
  if (detail.evidence) parts.push(String(detail.evidence))

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

  // --- AI kuzatuv ---
  if (detail.object) parts.push(String(detail.object))
  if (detail.direction) parts.push(GAZE_DIRECTION[detail.direction] || String(detail.direction))
  if (typeof detail.deviation === 'number') parts.push(`${detail.deviation}°`)
  if (typeof detail.similarity === 'number') parts.push(`o‘xshashlik ${detail.similarity}`)
  if (detail.module) parts.push(`modul: ${MODULE_LABEL[detail.module] || detail.module}`)
  // Davomiylik hodisaning JIDDIYLIGINI belgilaydi: bir soniyalik
  // "chetga qaradi" tabiiy, o'n soniyalik esa emas.
  if (typeof detail.duration_ms === 'number' && detail.duration_ms >= 1000) {
    parts.push(`${Math.round(detail.duration_ms / 1000)} s`)
  }
  if (typeof detail.confidence === 'number') parts.push(`ishonch ${detail.confidence}%`)
  // Birlashtirilgan xulosaning ASOSI. Usiz "yuqori shubha" yorlig'i
  // tekshirib bo'lmaydigan da'vo bo'lib qolardi.
  if (Array.isArray(detail.fused_from) && detail.fused_from.length) {
    parts.push(detail.fused_from.map((type) => EVENT_LABEL[type] || type).join(' + '))
  }
  if (detail.camera_role) parts.push(CAMERA_ROLE[detail.camera_role] || String(detail.camera_role))

  return parts.join(' • ')
}

/** Nigoh yo'nalishi — operator qaysi tomonga qarashini bilishi kerak. */
const GAZE_DIRECTION = {
  left: 'chapga',
  right: 'o‘ngga',
  up: 'yuqoriga',
  down: 'pastga',
}

/** Qaysi kamera ko'rdi. */
const CAMERA_ROLE = {
  primary: 'asosiy kamera',
  secondary: 'ikkinchi kamera',
}

/** `proctoring_degraded` — qaysi modul ishlamadi. */
const MODULE_LABEL = {
  identity: 'shaxs',
  objects: 'obyekt',
  pose: 'poza',
  gaze: 'nigoh',
  // Klaviatura qulfi (client `lockdown`): yopishgan tugma yoki Windows
  // olib tashlagan hook — talabgorning harakati emas.
  keyboard: 'klaviatura qulfi',
}

/** `peripheral_*` — qurilma turi (client `services/peripherals.py:KINDS`). */
const PERIPHERAL_KIND = {
  storage: 'disk / fleshka',
  phone: 'telefon',
  network: 'tarmoq / modem',
  audio: 'audio (naushnik)',
  bluetooth: 'Bluetooth',
  camera: 'kamera',
  input: 'sichqoncha / klaviatura',
  other: 'boshqa qurilma',
}

/** Client yuboradigan sabab kodlari — o'qiladigan matnga. */
const ANOMALY_KIND = {
  identical_frames: 'bir xil kadrlar',
  app_hash_changed: 'dastur fayli o‘zgargan',
  fingerprint_changed: 'apparat izi o‘zgargan',
  fingerprint_shared: 'bir apparatda bir necha qurilma',
  download: 'yuklab olishga urinish',
  stuck_key: 'tugma yopishib qolgan — qo‘yib yuborildi',
  hook_restored: 'Windows o‘chirgan qulf qayta o‘rnatildi',
  hook_lost: 'qulf ishlamayapti',
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
