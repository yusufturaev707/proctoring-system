import { Chip, Stack, Tooltip, Typography } from '@mui/material'
import CircleIcon from '@mui/icons-material/Circle'
import { useOptions } from '../../components/data/useResource'
import {
  cameras as camerasApi, cocoGroups as cocoGroupsApi, computers as computersApi,
  examSchedules as examSchedulesApi, examTypes as examTypesApi,
  exams as examsApi, permissions as permissionsApi, regions as regionsApi,
  roles as rolesApi, settings as settingsApi, users as usersApi, zones as zonesApi,
} from '../../api/endpoints'
import { COMPUTER_STATUS_LABEL, formatDateTime, fromNow } from '../../utils/labels'

/**
 * Faol/nofaol ustuni — faqat O'QISH uchun.
 *
 * `ResourcePage` ning `toggleField` prop'i bor va aksariyat sahifalar
 * shundan foydalanadi (bir bosishda o'zgartiradi). Bu komponent esa
 * o'zgartirib bo'lmaydigan holatlar uchun qoladi — masalan foydalanuvchi
 * o'z hisobini bloklay olmasligi kerak bo'lgan joyda.
 */
export function BoolCell(params) {
  return (
    <Chip
      size="small"
      color={params.value ? 'success' : 'default'}
      variant={params.value ? 'filled' : 'outlined'}
      label={params.value ? 'Faol' : 'Nofaol'}
    />
  )
}

/** Qurilma holatining matnli ko'rinishi — CSV eksporti uchun. */
export const deviceStatusText = (value) => COMPUTER_STATUS_LABEL[value] || value || ''

/** Qurilma holati (online/offline/imtihonda). */
export function DeviceStatusCell(params) {
  const value = params.value
  const color = value === 'in_exam' ? 'warning' : value === 'online' ? 'success' : value === 'blocked' ? 'error' : 'default'
  return (
    <Stack direction="row" spacing={0.75} alignItems="center" sx={{ height: '100%' }}>
      <CircleIcon sx={{ fontSize: 9 }} color={color === 'default' ? 'disabled' : color} />
      <Typography variant="body2">{COMPUTER_STATUS_LABEL[value] || value}</Typography>
    </Stack>
  )
}

/** Oxirgi faollik — nisbiy vaqt, tooltip'da aniq sana. */
export function LastSeenCell(params) {
  // `height: 100%` + markaz: maxsus `renderCell` DataGrid'ning oddiy
  // matnli kataklaridan farqli ravishda o'zi tekislanmaydi va qatorning
  // yuqorisiga yopishib qolardi.
  const cell = { height: '100%', display: 'flex', alignItems: 'center' }
  if (!params.value) {
    return <Typography variant="body2" color="text.disabled" sx={cell}>—</Typography>
  }
  return (
    <Tooltip title={formatDateTime(params.value)}>
      <Typography variant="body2" sx={cell}>{fromNow(params.value)}</Typography>
    </Tooltip>
  )
}

/** Raqamli ustun uchun "0 bo'lsa chiziqcha". */
export function countCell(params) {
  return params.value > 0
    ? <Typography variant="body2" fontWeight={600}>{params.value}</Typography>
    : <Typography variant="body2" color="text.disabled">—</Typography>
}

// --------------------------------------------------------------------------
// Select variantlari — barcha CRUD sahifalarida qayta ishlatiladi.
// Uzoq keshlanadi (5 daq), chunki bu ma'lumot kam o'zgaradi.
// --------------------------------------------------------------------------
export const useRegionOptions = () =>
  useOptions('regions', regionsApi, (item) => ({ value: item.id, label: item.name }))

/**
 * Binolar.
 *
 * Har bir variant o'z viloyati ID'sini olib yuradi — «avval viloyat,
 * keyin o'sha viloyatning binolari» zanjiri shu maydonga tayanadi va
 * har bir viloyat almashganda serverga qayta so'rov ketmaydi.
 */
export const useZoneOptions = () =>
  useOptions('zones', zonesApi, (item) => ({
    value: item.id,
    label: `${item.name} — ${item.region_name}`,
    // Zanjirda viloyat tanlangach yorliqda uni takrorlash ortiqcha.
    shortLabel: item.number ? `${item.name} (${item.number})` : item.name,
    region: item.region,
  }))

export const useExamOptions = () =>
  useOptions('exams', examsApi, (item) => ({ value: item.id, label: item.name }))

/**
 * Test sessiyalari (imtihon jadvali) — bron sahifasi uchun.
 *
 * Yorliq uch qismli: imtihon, vaqt va bino. Bir kunda bitta imtihonning
 * bir nechta seansi bo'ladi va ular faqat vaqt/bino bilan farqlanadi.
 */
export const useScheduleOptions = () =>
  useOptions('exam-schedules', examSchedulesApi, (item) => ({
    value: item.id,
    label: `${item.exam_name} · ${formatDateTime(item.starts_at).slice(0, 16)} · ${
      item.zone_name || 'Barcha binolar'
    }`,
    exam: item.exam_name,
    startsAt: item.starts_at,
    endsAt: item.ends_at,
    zone: item.zone,
    zoneName: item.zone_name,
    isOpen: item.is_open,
    isActive: item.is_active,
  }))

export const useExamTypeOptions = () =>
  useOptions('exam-types', examTypesApi, (item) => ({ value: item.id, label: item.name }))

export const useCocoGroupOptions = () =>
  useOptions('coco-groups', cocoGroupsApi, (item) => ({ value: item.id, label: item.name }))

export const useRoleOptions = () =>
  useOptions('roles', rolesApi, (item) => ({ value: item.id, label: item.name }))

export const useCameraOptions = () =>
  useOptions('cameras', camerasApi, (item) => ({
    value: item.id,
    label: `${item.name} (${item.ip_address})`,
    zone: item.zone,
    region: item.region,
  }))

/**
 * Zanjirli tanlov uchun yordamchilar.
 *
 * Filtrlash mijozda bajariladi: binolar va kameralar ro'yxati
 * `useOptions` orqali allaqachon to'liq olingan va 5 daqiqa keshda
 * turadi. Har bir viloyat almashganda serverga borish shu keshni
 * bekorga tashlab yuborardi.
 */
export const zonesOfRegion = (options, regionId) =>
  regionId
    ? options
        .filter((option) => String(option.region) === String(regionId))
        .map((option) => ({ ...option, label: option.shortLabel || option.label }))
    : []

/**
 * Filtr juftligi: Viloyat -> shu viloyatning binolari.
 *
 * Ilgari ko'p sahifada faqat «Bino» filtri bor edi va unda BARCHA
 * viloyatlarning yuzlab binosi bitta ro'yxatda turardi. Bino filtri
 * viloyat tanlanmaguncha ham ishlaydi (hamma binolar, viloyati bilan),
 * tanlangach — faqat o'sha viloyatniki; viloyat almashsa bino tozalanadi.
 * Viloyat foydalanuvchisida viloyat filtri yashiriladi (`regionScope`).
 *
 * `region` / `zone` — server filtr nomlari (`zone__region`,
 * `computer__zone__region`, `session__zone__region` ...).
 */
export const regionZoneFilters = ({
  region = 'zone__region', zone = 'zone', regionOptions, zoneOptions,
}) => [
  {
    name: region, label: 'Viloyat', type: 'select', options: regionOptions,
    resets: [zone], regionScope: true,
  },
  {
    name: zone, label: 'Bino', type: 'select',
    options: (filters) => (filters[region] ? zonesOfRegion(zoneOptions, filters[region]) : zoneOptions),
  },
]

export const camerasOfZone = (options, zoneId) =>
  zoneId ? options.filter((option) => String(option.zone) === String(zoneId)) : []

/**
 * Kompyuterlar - kamera biriktirish formasi uchun.
 *
 * Yorliqda inventar kodi bilan birga bino ham ko'rsatiladi: bir
 * markazda `PC-0007` kodi bir necha binoda uchraydi (kod faqat TIRIK
 * yozuvlar orasida unikal) va operator qaysi mashinani tanlayotganini
 * ko'rishi kerak.
 */
export const useComputerOptions = () =>
  useOptions('computers', computersApi, (item) => ({
    value: item.id,
    // NOM SERVERDAN (`label`): "№12 · INV-001". Uni bu yerda
    // yasash raqamsiz mashinada "№null" berardi va qoida ikki
    // joyda yashardi.
    label: `${item.label || item.inventory_code} — ${item.zone_name}`,
    shortLabel: item.label || item.inventory_code,
    zone: item.zone,
    region: item.region,
  }))

export const computersOfZone = (options, zoneId) =>
  zoneId
    ? options
        .filter((option) => String(option.zone) === String(zoneId))
        .map((option) => ({ ...option, label: option.shortLabel || option.label }))
    : []

export const useSettingOptions = () =>
  useOptions('settings', settingsApi, (item) => ({
    value: item.id,
    label: item.is_active ? `${item.name} (global standart)` : item.name,
  }))

/** Audit filtrida "kim" ustuni uchun. */
export const useUserOptions = () =>
  useOptions('users', usersApi, (item) => ({
    value: item.id,
    label: item.full_name ? `${item.username} — ${item.full_name}` : item.username,
  }))

/**
 * Ruxsatlar ro'yxati.
 *
 * `PermissionViewSet` da `pagination_class = None` — javob xom massiv,
 * `{results: [...]}` emas. `useOptions` ikkala shaklni ham tushunadi.
 */
export const usePermissionOptions = () =>
  useOptions('permissions', permissionsApi, (item) => ({
    value: item.id,
    label: item.name,
    group: item.group,
  }))
