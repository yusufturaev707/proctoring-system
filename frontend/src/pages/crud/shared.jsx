import { Chip, Stack, Tooltip, Typography } from '@mui/material'
import CircleIcon from '@mui/icons-material/Circle'
import { useOptions } from '../../components/data/useResource'
import {
  cameras as camerasApi, cocoGroups as cocoGroupsApi, examTypes as examTypesApi,
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
    <Stack direction="row" spacing={0.75} alignItems="center">
      <CircleIcon sx={{ fontSize: 9 }} color={color === 'default' ? 'disabled' : color} />
      <Typography variant="body2">{COMPUTER_STATUS_LABEL[value] || value}</Typography>
    </Stack>
  )
}

/** Oxirgi faollik — nisbiy vaqt, tooltip'da aniq sana. */
export function LastSeenCell(params) {
  if (!params.value) return <Typography variant="body2" color="text.disabled">—</Typography>
  return (
    <Tooltip title={formatDateTime(params.value)}>
      <Typography variant="body2">{fromNow(params.value)}</Typography>
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

export const camerasOfZone = (options, zoneId) =>
  zoneId ? options.filter((option) => String(option.zone) === String(zoneId)) : []

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
