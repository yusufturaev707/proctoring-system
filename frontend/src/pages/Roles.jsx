import { useCallback, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Box, Chip, Stack, Tooltip, Typography } from '@mui/material'
import BadgeIcon from '@mui/icons-material/BadgeOutlined'
import InfoIcon from '@mui/icons-material/InfoOutlined'
import PublicIcon from '@mui/icons-material/PublicOutlined'
import KeyIcon from '@mui/icons-material/VpnKeyOutlined'

import ResourcePage from '../components/data/ResourcePage'
import { useOptions } from '../components/data/useResource'
import PermissionMatrix from '../components/users/PermissionMatrix'
import { SurfaceChips } from '../components/users/UserBits'
import { FULL_ACCESS, surfacesOf } from '../components/users/permissionMeta'
import { permissions as permissionsApi, roles as rolesApi } from '../api/endpoints'
import { useAuth } from '../context/AuthContext'

const cell = { height: '100%', display: 'flex', alignItems: 'center' }

// Modul darajasida: `useOptions` mapper'i har renderda yangi funksiya
// bo'lsa, variantlar ham har safar qayta hisoblanardi.
const roleKeyMapper = (item) => ({ value: item.id, key: item.key })

const FORM_SECTIONS = {
  'Asosiy': { icon: BadgeIcon, description: 'Rol nomi panelda va foydalanuvchi kartasida ko‘rinadi' },
  'Qamrov va holat': { icon: PublicIcon, description: 'Xodim qaysi viloyatlar ma’lumotini ko‘radi' },
  'Ruxsatlar': { icon: KeyIcon, description: 'Rol qayerda ishlaydi va qaysi amallarni bajara oladi' },
}

const codesOf = (row) => (row.permissions || []).map((item) => item.code)

export default function Roles() {
  const { can } = useAuth()

  // `PermissionViewSet` da `pagination_class = None` — javob xom massiv.
  // Katalog TO'LIQ keladi (barcha guruhlar), matritsa shundan chiziladi.
  const { data: permissionsData } = useQuery({
    queryKey: ['permissions'],
    queryFn: () => permissionsApi.list(),
    staleTime: 10 * 60 * 1000,
  })
  const permissionList = useMemo(
    () => (Array.isArray(permissionsData) ? permissionsData : (permissionsData?.results || [])),
    [permissionsData],
  )

  // Yangi rolga keyingi bo'sh kalit — administrator raqam o'ylab topmasin.
  const { options: roleKeys } = useOptions('roles', rolesApi, roleKeyMapper)
  const nextKey = useMemo(
    () => roleKeys.reduce((top, role) => Math.max(top, role.key || 0), 0) + 1,
    [roleKeys],
  )

  const renderMatrix = useCallback(
    ({ value, onChange, disabled }) => (
      <PermissionMatrix
        permissions={permissionList}
        selected={Array.isArray(value) ? value : []}
        onChange={onChange}
        disabled={disabled}
        // Server qoidasi bilan bir xil (`RoleSerializer.validate`): o'zida
        // yo'q ruxsatni rolga qo'shib bo'lmaydi.
        canGrant={can}
      />
    ),
    [permissionList, can],
  )

  return (
    <ResourcePage
      // Barcha viloyatlar uchun bitta yozuv — o'zgartirish respublika darajasida.
      shared
      title="Rollar va ruxsatlar"
      subtitle="Har bir rol qayerda ishlashi (panel / client) va qaysi amallarni bajara olishi"
      queryKey="roles"
      api={rolesApi}
      permission="users.manage"
      searchPlaceholder="Rol nomi bo‘yicha…"
      defaultSort={{ field: 'key', sort: 'asc' }}
      defaults={{ is_active: true, is_global: false, permission_ids: [], key: nextKey }}
      getRowLabel={(row) => row?.name}
      formMaxWidth="lg"
      formIcon={<BadgeIcon />}
      formTitle={(isEdit, row) => (isEdit ? `«${row?.name}» rolini tahrirlash` : 'Yangi rol')}
      formSections={FORM_SECTIONS}
      formDescription="O‘zgarish darhol kuchga kiradi — xodim keyingi so‘rovidayoq yangi huquqlar bilan ishlaydi."
      exportName="rollar"
      height={560}
      // Rolni o'chirish unga biriktirilgan xodimlarni ruxsatsiz qoldiradi
      // (server xodimli rolni o'chirmaydi — `role_in_use`).
      deleteConfirmPhrase
      deleteDescription="Rolni faqat unga hech kim biriktirilmagan bo‘lsa o‘chirish mumkin. Avval xodimlarga boshqa rol bering."
      toggleField="is_active"
      columns={[
        { field: 'key', headerName: 'Kalit', width: 80 },
        {
          field: 'name', headerName: 'Rol', flex: 1, minWidth: 220,
          renderCell: (params) => (
            <Stack direction="row" spacing={1} alignItems="center" sx={{ ...cell, minWidth: 0 }}>
              <Typography variant="body2" fontWeight={650} noWrap>{params.value}</Typography>
              {params.row.description && (
                <Tooltip title={params.row.description}>
                  <InfoIcon sx={{ fontSize: 16, color: 'text.disabled' }} />
                </Tooltip>
              )}
            </Stack>
          ),
        },
        {
          field: 'surfaces', headerName: 'Qayerda ishlaydi', width: 190, sortable: false,
          valueGetter: (_value, row) => surfacesOf(codesOf(row)),
          // `exportValue` xom qiymatni oladi (`valueGetter` natijasini emas).
          exportValue: (_value, row) => {
            const { panel, client } = surfacesOf(codesOf(row))
            return [panel && 'Admin panel', client && 'Desktop client'].filter(Boolean).join(', ')
          },
          renderCell: (params) => <Box sx={cell}><SurfaceChips {...params.value} /></Box>,
        },
        {
          field: 'permissions', headerName: 'Ruxsatlar', width: 130, sortable: false,
          // Eksportda chip emas, son chiqishi kerak.
          valueGetter: (value) => value?.length || 0,
          exportValue: (value, row) => (codesOf(row).includes(FULL_ACCESS) ? 'To‘liq' : value),
          renderCell: (params) =>
            codesOf(params.row).includes(FULL_ACCESS)
              ? <Chip size="small" color="primary" label="To‘liq huquq" />
              : <Chip size="small" icon={<KeyIcon />} label={params.value} variant="outlined" />,
        },
        {
          field: 'is_global', headerName: 'Qamrov', width: 125, sortable: false,
          exportValue: (value) => (value ? 'Respublika' : 'Viloyat'),
          renderCell: (params) => (
            <Chip
              size="small"
              color={params.value ? 'warning' : 'default'}
              variant={params.value ? 'filled' : 'outlined'}
              label={params.value ? 'Respublika' : 'Viloyat'}
            />
          ),
        },
        {
          field: 'users_count', headerName: 'Xodimlar', width: 100, sortable: false,
          align: 'right', headerAlign: 'right',
          renderCell: (params) =>
            params.value > 0
              ? <Typography variant="body2" fontWeight={600} sx={{ ...cell, justifyContent: 'flex-end' }}>{params.value}</Typography>
              : <Typography variant="body2" color="text.disabled" sx={{ ...cell, justifyContent: 'flex-end' }}>—</Typography>,
        },
      ]}
      filters={[
        {
          name: 'is_global', label: 'Qamrov', type: 'select',
          options: [
            { value: 'true', label: 'Respublika' },
            { value: 'false', label: 'Viloyat' },
          ],
        },
        {
          name: 'is_active', label: 'Holat', type: 'select',
          options: [{ value: 'true', label: 'Faol' }, { value: 'false', label: 'Nofaol' }],
        },
      ]}
      fields={[
        { name: 'name', label: 'Rol nomi', required: true, maxLength: 150, colSpan: 8, section: 'Asosiy' },
        {
          name: 'key', label: 'Kalit', type: 'number', required: true,
          min: 0, max: 32767, integer: true, colSpan: 4, section: 'Asosiy',
          helperText: 'Raqamli identifikator — tizim bo‘ylab unikal',
        },
        {
          name: 'description', label: 'Izoh', type: 'textarea', maxLength: 500, nullable: false, colSpan: 12, section: 'Asosiy',
          helperText: 'Rol kim uchun va nima qiladi — rol tanlashda ko‘rinadi',
        },
        {
          name: 'is_global', label: 'Butun respublika bo‘yicha', type: 'boolean', colSpan: 6,
          section: 'Qamrov va holat',
          helperText:
            'Barcha viloyatlarni ko‘radi, viloyat biriktirish shart emas. O‘chiq — faqat o‘z viloyati.',
        },
        {
          name: 'is_active', label: 'Faol', type: 'boolean', colSpan: 6, section: 'Qamrov va holat',
          helperText: 'Nofaol rol hech qanday huquq bermaydi — xodimlar tizimga kira olmaydi',
        },
        {
          name: 'permission_ids',
          type: 'custom',
          colSpan: 12,
          section: 'Ruxsatlar',
          render: renderMatrix,
          // Serializer o'qishda to'liq obyektlarni (`permissions`), yozishda
          // esa ID massivini (`permission_ids`) kutadi — shuning uchun
          // boshlang'ich qiymatni boshqa maydondan olamiz.
          readFrom: (row) => (row.permissions || []).map((item) => item.id),
          validate: (value) =>
            Array.isArray(value) && value.length === 0
              ? 'Kamida bitta ruxsat tanlang — aks holda rol hech narsa bera olmaydi'
              : null,
        },
      ]}
    />
  )
}
