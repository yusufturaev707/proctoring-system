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

export const NAVIGATION = [
  {
    section: 'Monitoring',
    items: [
      { label: 'Boshqaruv paneli', path: '/', icon: DashboardIcon, permission: 'dashboard.view' },
      { label: 'Jonli kuzatuv', path: '/live', icon: MonitorIcon, permission: 'sessions.view' },
      { label: 'Sessiyalar', path: '/sessions', icon: ListAltIcon, permission: 'sessions.view' },
      { label: 'Texnik muammolar', path: '/technical-problems', icon: BuildIcon, permission: 'technical.view' },
    ],
  },
  {
    section: 'Infratuzilma',
    items: [
      { label: 'Viloyatlar', path: '/regions', icon: MapIcon, permission: 'regions.view' },
      { label: 'Binolar', path: '/zones', icon: ApartmentIcon, permission: 'regions.view' },
      { label: 'Kompyuterlar', path: '/computers', icon: ComputerIcon, permission: 'devices.view' },
      { label: 'Kameralar', path: '/cameras', icon: VideocamIcon, permission: 'devices.view' },
      { label: 'Qurilma tokenlari', path: '/device-tokens', icon: SecurityIcon, permission: 'devices.view' },
    ],
  },
  {
    section: 'Imtihonlar',
    items: [
      { label: 'Imtihon turlari', path: '/exam-types', icon: CategoryIcon, permission: 'exams.view' },
      { label: 'Imtihonlar', path: '/exams', icon: SchoolIcon, permission: 'exams.view' },
      { label: 'Jadval', path: '/exam-schedules', icon: EventIcon, permission: 'exams.view' },
    ],
  },
  {
    // Client nazorati ALOHIDA bo'lim: bu sahifalar birgalikda "client
    // nima qiladi va qayerdan ulanadi" degan yagona mavzuni tashkil
    // qiladi va ular "Boshqaruv" ichida yo'qolib ketardi.
    section: 'Client nazorati',
    items: [
      { label: 'Client sozlamalari', path: '/settings', icon: TuneIcon, permission: 'controls.view' },
      { label: "Ruxsat etilgan IP'lar", path: '/allowed-ips', icon: LanIcon, permission: 'controls.ip_view' },
      { label: 'Chiqish parollari', path: '/exit-passwords', icon: LockIcon, permission: 'controls.exit_password_view' },
      { label: 'RDP dasturlar', path: '/rdp-objects', icon: ShieldIcon, permission: 'controls.view' },
      { label: 'Tezkor tugmalar', path: '/hotkeys', icon: KeyboardIcon, permission: 'controls.view' },
      { label: 'COCO obyektlar', path: '/coco-objects', icon: ScanIcon, permission: 'controls.view' },
      { label: 'COCO guruhlari', path: '/coco-groups', icon: LayersIcon, permission: 'controls.view' },
      { label: 'Model versiyalari', path: '/model-versions', icon: ModelIcon, permission: 'controls.view' },
    ],
  },
  {
    section: 'Boshqaruv',
    items: [
      { label: 'Foydalanuvchilar', path: '/users', icon: PeopleIcon, permission: 'users.view' },
      { label: 'Rollar', path: '/roles', icon: BadgeIcon, permission: 'users.view' },
      { label: 'Audit', path: '/audit', icon: HistoryIcon, permission: 'audit.view' },
    ],
  },
]
