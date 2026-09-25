import DashboardIcon from '@mui/icons-material/SpaceDashboardOutlined'
import MonitorIcon from '@mui/icons-material/MonitorHeartOutlined'
import ListAltIcon from '@mui/icons-material/ListAltOutlined'
import BuildIcon from '@mui/icons-material/BuildCircleOutlined'
import PeopleIcon from '@mui/icons-material/PeopleAltOutlined'
import BadgeIcon from '@mui/icons-material/BadgeOutlined'
import MapIcon from '@mui/icons-material/MapOutlined'
import ApartmentIcon from '@mui/icons-material/ApartmentOutlined'
import ComputerIcon from '@mui/icons-material/DesktopWindowsOutlined'
import VideocamIcon from '@mui/icons-material/VideocamOutlined'
import SecurityIcon from '@mui/icons-material/VerifiedUserOutlined'
import SchoolIcon from '@mui/icons-material/SchoolOutlined'
import CategoryIcon from '@mui/icons-material/CategoryOutlined'
import EventIcon from '@mui/icons-material/EventAvailableOutlined'
import TuneIcon from '@mui/icons-material/TuneOutlined'
import LanIcon from '@mui/icons-material/LanOutlined'
import ShieldIcon from '@mui/icons-material/GppMaybeOutlined'
import KeyboardIcon from '@mui/icons-material/KeyboardOutlined'
import LockIcon from '@mui/icons-material/LockOutlined'
import ScanIcon from '@mui/icons-material/CenterFocusStrongOutlined'
import LayersIcon from '@mui/icons-material/LayersOutlined'
import ModelIcon from '@mui/icons-material/MemoryOutlined'
import HistoryIcon from '@mui/icons-material/HistoryOutlined'
import PolicyIcon from '@mui/icons-material/PolicyOutlined'
import RiskIcon from '@mui/icons-material/SpeedOutlined'
import SeatIcon from '@mui/icons-material/EventSeatOutlined'

/**
 * Marshrut -> lazy import.
 *
 * Bitta joyda saqlanadi, chunki u ikki maqsadda ishlatiladi:
 *   1. `App.jsx` da `React.lazy` uchun;
 *   2. Menyu ustiga sichqoncha kelganda oldindan yuklash (prefetch) uchun.
 *
 * Prefetch — sezilarli tezlik yutug'i: foydalanuvchi bosgunicha
 * (~200–400 ms) chunk allaqachon yuklab bo'lingan bo'ladi va sahifa
 * "kutishsiz" ochiladi.
 */
export const ROUTE_LOADERS = {
  '/': () => import('../pages/Dashboard'),
  '/live': () => import('../pages/LiveMonitor'),
  '/sessions': () => import('../pages/Sessions'),
  '/technical-problems': () => import('../pages/TechnicalProblems'),
  '/regions': () => import('../pages/crud/RegionsPage'),
  '/zones': () => import('../pages/crud/ZonesPage'),
  '/computers': () => import('../pages/crud/ComputersPage'),
  '/cameras': () => import('../pages/crud/CamerasPage'),
  '/device-tokens': () => import('../pages/DeviceTokens'),
  '/exam-types': () => import('../pages/crud/ExamTypesPage'),
  '/exams': () => import('../pages/crud/ExamsPage'),
  '/exam-schedules': () => import('../pages/crud/ExamSchedulesPage'),
  '/computer-bookings': () => import('../pages/ComputerBookings'),
  '/users': () => import('../pages/Users'),
  '/roles': () => import('../pages/Roles'),
  '/settings': () => import('../pages/Settings'),
  '/allowed-ips': () => import('../pages/crud/AllowedIpsPage'),
  '/exit-passwords': () => import('../pages/crud/ClientExitPasswordsPage'),
  '/rdp-objects': () => import('../pages/crud/RdpObjectsPage'),
  '/hotkeys': () => import('../pages/crud/HotkeysPage'),
  '/coco-objects': () => import('../pages/crud/CocoObjectsPage'),
  '/coco-groups': () => import('../pages/crud/CocoGroupsPage'),
  '/model-versions': () => import('../pages/crud/ModelVersionsPage'),
  '/proctoring-policies': () => import('../pages/crud/ProctoringPoliciesPage'),
  '/risk-weights': () => import('../pages/crud/RiskWeightsPage'),
  '/audit': () => import('../pages/AuditLogs'),
  '/profile': () => import('../pages/Profile'),
}

const prefetched = new Set()

export function prefetchRoute(path) {
  if (prefetched.has(path)) return
  const loader = ROUTE_LOADERS[path]
  if (!loader) return
  prefetched.add(path)
  // Xatoni yutamiz: prefetch — optimizatsiya, u muvaffaqiyatsiz bo'lsa
  // haqiqiy navigatsiya baribir chunk'ni qayta so'raydi.
  loader().catch(() => prefetched.delete(path))
}

/**
 * Menyu tuzilishi.
 *
 * HAR BIR BAND `description` ga EGA va u uch joyda ko'rinadi: yig'ilgan
 * menyudagi tooltip, qidiruv oynasi (Ctrl+K) va sahifa sarlavhasidagi
 * "i" belgisi. Savol har doim bir xil — "bu sahifa NIMA UCHUN kerak?".
 * Sahifaning o'z `subtitle` i esa boshqa savolga javob beradi ("bu
 * yerda nima bor"), shuning uchun ular takrorlanmaydi.
 *
 * NOMLAR ISH TILIDA, TEXNIK ATAMADA EMAS. "COCO obyektlar", "RDP
 * dasturlar", "Qurilma tokenlari" — ichki atamalar: operator ulardan
 * sahifa nimani boshqarishini bilib ololmasdi. Marshrutlar (`path`)
 * o'zgarmagan — xatcho'plar va hujjatdagi havolalar ishlayveradi.
 *
 * BO'LIMLAR MAVZU BO'YICHA, ruxsat bo'yicha emas. Ilgari obyekt
 * ro'yxatlari va model versiyalari "Client nazorati" da turardi,
 * holbuki ular AI kuzatuvning qismi — administrator YOLO sozlamasini
 * qidirib ikki bo'lim orasida yurardi. Ruxsat har bir band uchun
 * alohida tekshiriladi (`permission`), ya'ni bitta bo'limda turli
 * ruxsatli bandlar bo'lishi xavfsiz.
 */
export const NAVIGATION = [
  {
    section: 'Monitoring',
    items: [
      {
        label: 'Boshqaruv paneli', path: '/', icon: DashboardIcon, permission: 'dashboard.view',
        description: 'Bugungi umumiy holat: faol sessiyalar, hodisalar va binolar kesimi',
      },
      {
        label: 'Jonli kuzatuv', path: '/live', icon: MonitorIcon, permission: 'sessions.view',
        description: 'Hozir ketayotgan imtihonlar: ogohlantirish yuborish va chetlashtirish',
      },
      {
        label: 'Sessiyalar', path: '/sessions', icon: ListAltIcon, permission: 'sessions.view',
        description: 'Barcha imtihon sessiyalari: dalillar, skrinshotlar va bayonnoma',
      },
      {
        label: 'Texnik muammolar', path: '/technical-problems', icon: BuildIcon, permission: 'technical.view',
        description: 'Imtihon paytidagi nosozliklar va qo‘shimcha vaqt berish qarorlari',
      },
    ],
  },
  {
    section: 'Imtihonlar',
    items: [
      {
        label: 'Imtihonlar', path: '/exams', icon: SchoolIcon, permission: 'exams.view',
        description: 'Test platformasi bilan bog‘lanish va imtihon sozlama profili',
      },
      {
        label: 'Imtihon jadvali', path: '/exam-schedules', icon: EventIcon, permission: 'exams.view',
        description: 'Kirish oynalari — talabgor faqat shu vaqtda JSHSHIR kirita oladi',
      },
      {
        label: 'Kompyuter bronlari', path: '/computer-bookings', icon: SeatIcon, permission: 'bookings.view',
        description: 'Talabgorlarni kompyuterlarga biriktirish — client joyni tekshiradi',
      },
      {
        label: 'Imtihon turlari', path: '/exam-types', icon: CategoryIcon, permission: 'exams.view',
        description: 'Imtihonlarni guruhlash uchun ma’lumotnoma',
      },
    ],
  },
  {
    section: 'Infratuzilma',
    items: [
      {
        label: 'Viloyatlar', path: '/regions', icon: MapIcon, permission: 'regions.view',
        description: 'Hududlar — xodimlarning ko‘rish doirasi shu bo‘yicha cheklanadi',
      },
      {
        label: 'Binolar', path: '/zones', icon: ApartmentIcon, permission: 'regions.view',
        description: 'Imtihon markazlari: kompyuter, kamera va jadval shu yerga bog‘lanadi',
      },
      {
        label: 'Kompyuterlar', path: '/computers', icon: ComputerIcon, permission: 'devices.view',
        description: 'Ish o‘rinlari: xonadagi raqam, MAC manzil va onlayn holat',
      },
      {
        label: 'Kameralar', path: '/cameras', icon: VideocamIcon, permission: 'devices.view',
        description: 'Binodagi IP kameralar: ulanish holati va jonli ko‘rish',
      },
      {
        label: 'Client qurilmalari', path: '/device-tokens', icon: SecurityIcon, permission: 'devices.view',
        description: 'O‘rnatilgan client dasturlari: tasdiqlash, bloklash, kompyuterga biriktirish',
      },
    ],
  },
  {
    section: 'Client nazorati',
    items: [
      {
        label: 'Client sozlamalari', path: '/settings', icon: TuneIcon, permission: 'controls.view',
        description: 'Sozlama profillari: skrinshot, FaceID chegarasi, bloklash qoidalari',
      },
      {
        label: "Ruxsat etilgan IP'lar", path: '/allowed-ips', icon: LanIcon, permission: 'controls.ip_view',
        description: 'Client faqat shu tashqi manzillardan kira oladi',
      },
      {
        label: 'Chiqish parollari', path: '/exit-passwords', icon: LockIcon, permission: 'controls.exit_password_view',
        description: 'Client dasturini yopish uchun viloyat paroli (Ctrl+Q)',
      },
      {
        label: 'Taqiqlangan dasturlar', path: '/rdp-objects', icon: ShieldIcon, permission: 'controls.view',
        description: 'Masofaviy boshqaruv va virtualizatsiya dasturlari — topilsa yopiladi',
      },
      {
        label: 'Tezkor tugmalar', path: '/hotkeys', icon: KeyboardIcon, permission: 'controls.view',
        description: 'Imtihon paytida bloklanadigan klaviatura kombinatsiyalari',
      },
    ],
  },
  {
    // AI kuzatuv bandlari chetlashtirish qaroriga bevosita ta'sir
    // qiladi (xavf balli, tasdiqlash chegaralari), shuning uchun
    // ular bitta joyda va "Client nazorati" dan ALOHIDA.
    section: 'AI kuzatuv',
    items: [
      {
        label: 'Kuzatuv siyosati', path: '/proctoring-policies', icon: PolicyIcon,
        permission: 'controls.proctoring_view',
        description: 'Kamera talablari, AI modullari va hodisa qachon shubha hisoblanishi',
      },
      {
        label: 'Hodisa og‘irliklari', path: '/risk-weights', icon: RiskIcon,
        permission: 'controls.proctoring_view',
        description: 'Har bir hodisa xavf balliga qancha qo‘shadi va qanchalik tez takrorlanadi',
      },
      {
        label: 'Taqiqlangan obyektlar', path: '/coco-objects', icon: ScanIcon, permission: 'controls.view',
        description: 'Kamera kadrida qidiriladigan narsalar: telefon, kitob, noutbuk…',
      },
      {
        label: 'Obyekt guruhlari', path: '/coco-groups', icon: LayersIcon, permission: 'controls.view',
        description: 'Taqiqlangan obyektlarni mavzu bo‘yicha guruhlash',
      },
      {
        label: 'Model versiyalari', path: '/model-versions', icon: ModelIcon, permission: 'controls.view',
        description: 'Client ishlatadigan obyekt aniqlash (YOLO) modellari',
      },
    ],
  },
  {
    section: 'Tizim',
    items: [
      {
        label: 'Foydalanuvchilar', path: '/users', icon: PeopleIcon, permission: 'users.view',
        description: 'Xodimlar hisoblari, rol va viloyat biriktiruvi',
      },
      {
        label: 'Rollar', path: '/roles', icon: BadgeIcon, permission: 'users.view',
        description: 'Har bir rol qaysi amallarni bajara olishi',
      },
      {
        label: 'Audit jurnali', path: '/audit', icon: HistoryIcon, permission: 'audit.view',
        description: 'Kim, qachon, nima qildi — apellyatsiya uchun o‘zgarmas yozuvlar',
      },
    ],
  },
]

/** Profil menyuda emas (u yon panel pastida), lekin qidiruvda bo'lishi kerak. */
export const PROFILE_ITEM = {
  label: 'Profil va sozlamalar',
  path: '/profile',
  permission: null,
  description: 'Parol, rang sxemasi, tungi rejim va zichlik',
}

/**
 * Joriy manzilga mos menyu bandi va uning bo'limi.
 *
 * Eng UZUN mos yo'l tanlanadi: `/sessions/42` -> "Sessiyalar", `/` esa
 * faqat aniq mos kelganda. Aks holda har bir sahifa "Boshqaruv paneli"
 * ga tegishli bo'lib chiqardi.
 */
export function findNavEntry(pathname) {
  let best = null
  for (const group of NAVIGATION) {
    for (const item of group.items) {
      const matches = item.path === '/'
        ? pathname === '/'
        : pathname === item.path || pathname.startsWith(`${item.path}/`)
      if (matches && (!best || item.path.length > best.item.path.length)) {
        best = { section: group.section, item }
      }
    }
  }
  if (!best && pathname.startsWith(PROFILE_ITEM.path)) {
    return { section: 'Hisob', item: PROFILE_ITEM }
  }
  return best
}
