import DashboardIcon from '@mui/icons-material/SpaceDashboardOutlined'
import ListAltIcon from '@mui/icons-material/ListAltOutlined'
import BuildIcon from '@mui/icons-material/BuildCircleOutlined'
import PeopleIcon from '@mui/icons-material/PeopleAltOutlined'
import ComputerIcon from '@mui/icons-material/DesktopWindowsOutlined'
import MapIcon from '@mui/icons-material/MapOutlined'
import SchoolIcon from '@mui/icons-material/SchoolOutlined'
import TuneIcon from '@mui/icons-material/TuneOutlined'
import HistoryIcon from '@mui/icons-material/HistoryOutlined'
import DesktopIcon from '@mui/icons-material/DesktopMacOutlined'
import WebIcon from '@mui/icons-material/WebOutlined'
import ShieldIcon from '@mui/icons-material/AdminPanelSettingsOutlined'
import KeyIcon from '@mui/icons-material/VpnKeyOutlined'

/**
 * Ruxsatlar katalogining ko'rinishi — rol muharriri, foydalanuvchi
 * kartasi va jadvallar uchun BITTA joyda.
 *
 * Katalogning o'zi serverda (`users/services.py:DEFAULT_PERMISSIONS`);
 * bu yerda faqat guruh nomi, belgi va izoh. Ro'yxatda yo'q guruh ham
 * ko'rsatiladi (xom nomi bilan) — serverga yangi guruh qo'shilsa u
 * panelda jimgina yo'qolmasin.
 */

/** To'liq huquq — server `models.FULL_ACCESS_CODE`. */
export const FULL_ACCESS = '*'
/** Admin panelga kirish — server `models.PANEL_ACCESS_CODE`. */
export const PANEL_ACCESS = 'panel.access'
/** Desktop client'da ishlash (`ClientBaseView.required_permission`). */
export const CLIENT_OPERATE = 'client.operate'

/** Maxsus guruhlar matritsada alohida chiziladi, oddiy kartalar orasida emas. */
export const SPECIAL_GROUPS = new Set(['system', 'panel'])

export const GROUP_META = {
  system: { label: 'To‘liq huquq', icon: ShieldIcon },
  panel: { label: 'Admin panel', icon: WebIcon },
  dashboard: { label: 'Boshqaruv paneli', icon: DashboardIcon, description: 'Umumiy holat va statistika' },
  sessions: { label: 'Sessiyalar', icon: ListAltIcon, description: 'Kuzatuv, ogohlantirish, chetlashtirish, dalillar' },
  technical: { label: 'Texnik muammolar', icon: BuildIcon, description: 'Nosozliklar va qo‘shimcha vaqt qarorlari' },
  exams: { label: 'Imtihonlar', icon: SchoolIcon, description: 'Imtihon, jadval va kompyuter bronlari' },
  devices: { label: 'Qurilmalar', icon: ComputerIcon, description: 'Kompyuterlar, kameralar, client qurilmalari' },
  regions: { label: 'Hududlar', icon: MapIcon, description: 'Viloyatlar va binolar' },
  controls: { label: 'Sozlamalar', icon: TuneIcon, description: 'Client profili, IP ro‘yxati, chiqish paroli, AI siyosati' },
  users: { label: 'Foydalanuvchilar', icon: PeopleIcon, description: 'Xodimlar va rollar' },
  audit: { label: 'Audit', icon: HistoryIcon, description: 'Kim, qachon, nima qildi' },
  client: { label: 'Desktop client', icon: DesktopIcon, description: 'Imtihon markazidagi ish o‘rni (operator)' },
}

/** Ish tartibi bo'yicha — menyu tartibi bilan bir xil. */
const GROUP_ORDER = [
  'dashboard', 'sessions', 'technical', 'exams', 'devices', 'regions',
  'controls', 'users', 'audit', 'client',
]

export const groupMeta = (group) =>
  GROUP_META[group] || { label: group, icon: KeyIcon }

/**
 * Ruxsatlar ro'yxati -> `[{ group, meta, items }]` (tartiblangan).
 * `items` — `{ id?, code, name, group }`.
 */
export function groupPermissions(list, { includeSpecial = false } = {}) {
  const map = new Map()
  for (const item of list || []) {
    if (!includeSpecial && SPECIAL_GROUPS.has(item.group)) continue
    if (!map.has(item.group)) map.set(item.group, [])
    map.get(item.group).push(item)
  }
  const rank = (group) => {
    const index = GROUP_ORDER.indexOf(group)
    return index === -1 ? GROUP_ORDER.length : index
  }
  return [...map.entries()]
    .sort(([a], [b]) => rank(a) - rank(b) || a.localeCompare(b))
    .map(([group, items]) => ({ group, meta: groupMeta(group), items }))
}

/**
 * Kodlar to'plami `code` ni beradimi — server `models.codes_grant` bilan
 * bir xil (`*` va `guruh.*`).
 */
export function codesGrant(codes, code) {
  if (codes.includes(FULL_ACCESS) || codes.includes(code)) return true
  return codes.includes(`${code.split('.')[0]}.*`)
}

/** Rol/xodim qaysi yuzada ishlaydi — `{ panel, client }`. */
export function surfacesOf(codes) {
  return { panel: codesGrant(codes, PANEL_ACCESS), client: codesGrant(codes, CLIENT_OPERATE) }
}
