import { useCallback, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Box, Chip, IconButton, Stack, Tooltip, Typography } from '@mui/material'
import KeyIcon from '@mui/icons-material/VpnKeyOutlined'
import AccountIcon from '@mui/icons-material/AccountCircleOutlined'
import PersonIcon from '@mui/icons-material/PersonOutline'
import BadgeIcon from '@mui/icons-material/BadgeOutlined'
import PlaceIcon from '@mui/icons-material/PlaceOutlined'
import ToggleIcon from '@mui/icons-material/ToggleOnOutlined'
import ManageAccountsIcon from '@mui/icons-material/ManageAccountsOutlined'

import ResourcePage from '../components/data/ResourcePage'
import ConfirmDialog from '../components/ConfirmDialog'
import { listAll } from '../components/data/useResource'
import RolePicker from '../components/users/RolePicker'
import UserDetailDialog from '../components/users/UserDetailDialog'
import { SurfaceChips, UserAvatar } from '../components/users/UserBits'
import {
  LastSeenCell, useRegionOptions, useRoleOptions, useZoneOptions, zonesOfRegion,
} from './crud/shared'
import { roles as rolesApi, users as usersApi } from '../api/endpoints'
import { useAuth } from '../context/AuthContext'
import { useUi } from '../context/UiContext'

const cell = { height: '100%', display: 'flex', alignItems: 'center' }

const FORM_SECTIONS = {
  'Hisob': { icon: AccountIcon, description: 'Tizimga kirish uchun login va parol' },
  'Shaxsiy ma’lumotlar': { icon: PersonIcon, description: 'Audit jurnalida va kartada shu ism ko‘rinadi' },
  'Rol': { icon: BadgeIcon, description: 'Xodim qayerda ishlashi (panel / client) va nima qila olishi' },
  'Hudud': { icon: PlaceIcon, description: 'Viloyat darajasidagi rol faqat shu viloyat ma’lumotini ko‘radi' },
  'Holat': { icon: ToggleIcon },
}

export default function Users() {
  const { user: currentUser, can, canShared } = useAuth()
  const { notify, notifyError } = useUi()
  const canManage = can('users.manage')
  const { options: roleOptions } = useRoleOptions()
  const { options: regionOptions } = useRegionOptions()
  const { options: zoneOptions } = useZoneOptions()

  // Rol plitkalari uchun TO'LIQ rol obyektlari (ruxsatlari, qamrovi bilan).
  const { data: rolesData } = useQuery({
    queryKey: ['roles', 'picker'],
    queryFn: () => listAll(rolesApi),
    staleTime: 5 * 60 * 1000,
  })
  const roles = rolesData?.results
  const roleById = useMemo(
    () => Object.fromEntries((roles || []).map((role) => [String(role.id), role])),
    [roles],
  )

  const [detail, setDetail] = useState(null)
  const [resetTarget, setResetTarget] = useState(null)
  const [resetting, setResetting] = useState(false)

  const handleReset = async (password) => {
    setResetting(true)
    try {
      await usersApi.setPassword(resetTarget.id, password)
      notify(`${resetTarget.username} uchun parol yangilandi`)
      setResetTarget(null)
    } catch (error) {
      notifyError(error)
    } finally {
      setResetting(false)
    }
  }

  /**
   * Nega bu rolni BERA OLMAYDI — server qoidasining nusxasi
   * (`UserWriteSerializer.validate`), plitkani oldindan o'chirish uchun.
   */
  const blockedReason = useCallback(
    (role) => {
      if (!role.is_active) return 'Rol nofaol — avval «Rollar» sahifasida yoqing'
      if (currentUser?.is_superuser) return ''
      if (role.is_global && !canShared('users.manage')) {
        return 'Respublika darajasidagi rolni faqat respublika administratori beradi'
      }
      const missing = (role.permissions || []).filter((item) => !can(item.code))
      return missing.length ? 'Bu rolda sizda yo‘q ruxsatlar bor — uni bera olmaysiz' : ''
    },
    [currentUser, can, canShared],
  )

  const renderRolePicker = useCallback(
    ({ value, onChange, disabled, error, form }) => (
      <RolePicker
        roles={roles}
        value={value}
        onChange={onChange}
        // O'z rolini almashtirish taqiqlangan (server ham rad etadi).
        disabled={disabled || form?._meta?.row?.id === currentUser?.id}
        blockedReason={blockedReason}
        error={error}
      />
    ),
    [roles, blockedReason, currentUser],
  )

  const fields = useMemo(() => [
    {
      name: 'username', label: 'Login', required: true, maxLength: 150,
      pattern: 'slug', colSpan: 6, autoComplete: 'off', section: 'Hisob',
      // Login o'zgarishi audit izini uzadi va foydalanuvchini
      // chalkashtiradi — yaratilgandan keyin o'zgartirilmaydi.
      disabled: (_form, isEdit) => isEdit,
      helperText: (isEdit) =>
        isEdit ? 'Login o‘zgartirilmaydi' : 'Faqat harf, raqam, `-` va `_`',
    },
    {
      name: 'password', label: 'Parol', type: 'password', minLength: 3,
      colSpan: 6, password: true, clearable: false, section: 'Hisob',
      helperText: (isEdit) =>
        isEdit ? 'Bo‘sh qoldirilsa — o‘zgarmaydi' : 'Kamida 8 ta belgi, oddiy so‘z emas',
      validate: (value, form) => {
        // Yangi foydalanuvchi uchun parol majburiy, tahrirlashda esa
        // bo'sh bo'lishi mumkin — shuning uchun `required` emas.
        if (!form._meta?.isEdit && !value) return 'Yangi foydalanuvchi uchun parol shart'
        return null
      },
    },
    // `nullable: false`: modelda bo'sh satr (`default=""`), NULL emas —
    // tozalangan maydon `null` bo'lib ketsa server 400 qaytarardi.
    { name: 'last_name', label: 'Familiya', nullable: false, maxLength: 255, colSpan: 4, section: 'Shaxsiy ma’lumotlar' },
    { name: 'first_name', label: 'Ism', nullable: false, maxLength: 255, colSpan: 4, section: 'Shaxsiy ma’lumotlar' },
    { name: 'middle_name', label: 'Otasining ismi', nullable: false, maxLength: 255, colSpan: 4, section: 'Shaxsiy ma’lumotlar' },
    {
      name: 'phone', label: 'Telefon', nullable: false, maxLength: 20, colSpan: 6, section: 'Shaxsiy ma’lumotlar',
      pattern: { re: /^[+\d\s()-]{7,20}$/, message: 'Telefon formati noto‘g‘ri' },
      helperText: 'Masalan: +998 90 123 45 67',
    },
    {
      name: 'telegram_id', label: 'Telegram ID', maxLength: 32, colSpan: 6, section: 'Shaxsiy ma’lumotlar',
      helperText: 'Ixtiyoriy — bildirishnomalar uchun',
    },
    {
      name: 'role', type: 'custom', colSpan: 12, section: 'Rol',
      render: renderRolePicker,
      // Rolsiz hisob login qila olmaydi (`LoginSerializer`) — uni
      // yaratishdan ma'no yo'q.
      validate: (value) => (value ? null : 'Rolni tanlang — rolsiz xodim tizimga kira olmaydi'),
      helperText: (isEdit, form) =>
        form?._meta?.row?.id && form._meta.row.id === currentUser?.id
          ? 'O‘z rolingizni o‘zgartira olmaysiz — buni boshqa administrator qiladi'
          : '',
    },
    {
      name: 'region', label: 'Viloyat', type: 'select', options: regionOptions,
      colSpan: 6, section: 'Hudud', resets: ['zone'],
      helperText: (_isEdit, form) => {
        const role = roleById[String(form?.role ?? '')]
        if (!role) return 'Avval rolni tanlang'
        return role.is_global
          ? 'Respublika roli — bo‘sh qoldirilsa barcha viloyatlarni ko‘radi'
          : 'Viloyat darajasidagi rol — majburiy'
      },
      validate: (value, form) => {
        const role = roleById[String(form?.role ?? '')]
        return role && !role.is_global && !value ? 'Bu rol viloyat darajasida — viloyatni tanlang' : null
      },
    },
    {
      name: 'zone', label: 'Bino', type: 'select', colSpan: 6, section: 'Hudud',
      options: (form) => zonesOfRegion(zoneOptions, form.region),
      dependsOn: 'region',
      blockedText: 'Avval viloyatni tanlang',
      emptyOptionsText: 'Bu viloyatda bino yo‘q',
      helperText: 'Ixtiyoriy — xodim ishlaydigan imtihon markazi',
    },
    {
      name: 'is_active', label: 'Faol', type: 'boolean', colSpan: 6, section: 'Holat',
      // O'zini bloklab qo'yish — qaytarib bo'lmaydigan xato:
      // foydalanuvchi tizimdan chiqib ketadi va qayta kira olmaydi.
      disabled: (form) => form._meta?.row?.id === form._meta?.currentUserId,
      helperText: (isEdit, form) =>
        isEdit && form?._meta?.row?.id === form?._meta?.currentUserId
          ? 'O‘z hisobingizni bloklay olmaysiz'
          : 'O‘chirilsa — xodim panelga ham, client’ga ham kira olmaydi',
    },
    {
      name: 'is_staff', label: 'Django admin (/admin/)', type: 'boolean',
      colSpan: 6, section: 'Holat',
      // Serverda faqat superuser beradi — boshqalarga maydon ko'rsatilmaydi.
      hidden: () => !currentUser?.is_superuser,
      helperText: 'Faqat texnik xodimlar uchun',
    },
  ], [renderRolePicker, regionOptions, zoneOptions, roleById, currentUser])

  return (
    <>
      <ResourcePage
        title="Foydalanuvchilar"
        subtitle="Panel xodimlari va imtihon markazi operatorlari — qatorni bosing, to‘liq karta ochiladi"
        queryKey="users"
        api={usersApi}
        permission="users.manage"
        searchPlaceholder="Login, F.I.Sh. yoki telefon…"
        defaultSort={{ field: 'username', sort: 'asc' }}
        defaults={{
          is_active: true,
          // Viloyat admini faqat o'z viloyatiga xodim qo'sha oladi.
          region: currentUser?.is_region_scoped ? currentUser.region : '',
        }}
        getRowLabel={(row) => row?.username}
        actionsWidth={120}
        deleteConfirmPhrase
        deleteDescription="Foydalanuvchi o‘chirilsa, uning audit yozuvlari saqlanib qoladi (muallif nomi bilan). Vaqtincha to‘xtatish uchun «Faol» ni o‘chiring."
        formMaxWidth="md"
        formIcon={<ManageAccountsIcon />}
        formTitle={(isEdit, row) => (isEdit ? `${row?.full_name || row?.username} — tahrirlash` : 'Yangi foydalanuvchi')}
        formSections={FORM_SECTIONS}
        onRowClick={(params, { openEdit }) => setDetail({ row: params.row, openEdit })}
        columns={[
          {
            field: 'username', headerName: 'Xodim', flex: 1.6, minWidth: 200,
            exportValue: (value, row) => (row.full_name && row.full_name !== value ? `${row.full_name} (${value})` : value),
            renderCell: (params) => (
              <Stack direction="row" spacing={1.25} alignItems="center" sx={{ ...cell, minWidth: 0 }}>
                <UserAvatar user={params.row} size={26} />
                <Typography variant="body2" fontWeight={600} noWrap>
                  {params.row.full_name || params.value}
                </Typography>
                {params.row.full_name && params.row.full_name !== params.value && (
                  <Typography variant="caption" color="text.secondary" noWrap sx={{ fontFamily: 'monospace' }}>
                    {params.value}
                  </Typography>
                )}
              </Stack>
            ),
          },
          {
            field: 'role_name', headerName: 'Rol', width: 150, sortable: false,
            exportValue: (value, row) => (row.is_superuser ? 'Superuser' : value || ''),
            // Superuser hisob rol tekshiruvidan ham, viloyat filtridan ham
            // O'TADI (`HasRolePermission`, `User.is_region_scoped`) — u
            // "Biriktirilmagan" bo'lib ko'rinmasligi kerak.
            renderCell: (params) => {
              if (params.row.is_superuser) {
                return (
                  <Tooltip title="Tizim hisobi: barcha ruxsatlar va barcha viloyatlar. Rol tekshirilmaydi.">
                    <Chip size="small" color="warning" label="Superuser" />
                  </Tooltip>
                )
              }
              return params.value
                ? <Chip size="small" variant="outlined" label={params.value} />
                : <Typography variant="body2" color="error.main" sx={cell}>Biriktirilmagan</Typography>
            },
          },
          {
            field: 'surfaces', headerName: 'Qayerda ishlaydi', width: 155, sortable: false,
            exportValue: (value) =>
              (value || []).map((item) => (item === 'panel' ? 'Admin panel' : 'Desktop client')).join(', '),
            renderCell: (params) => (
              <Box sx={cell}>
                <SurfaceChips
                  panel={(params.value || []).includes('panel')}
                  client={(params.value || []).includes('client')}
                />
              </Box>
            ),
          },
          {
            field: 'region_name', headerName: 'Hudud', flex: 1, minWidth: 150, sortable: false,
            exportValue: (value, row) => [value || 'Barcha viloyatlar', row.zone_name].filter(Boolean).join(' · '),
            renderCell: (params) => (
              <Stack direction="row" spacing={0.75} alignItems="center" sx={{ ...cell, minWidth: 0 }}>
                <Typography variant="body2" noWrap color={params.value ? 'text.primary' : 'text.secondary'}>
                  {params.value || 'Barcha viloyatlar'}
                </Typography>
                {params.row.zone_name && (
                  <Typography variant="caption" color="text.secondary" noWrap>· {params.row.zone_name}</Typography>
                )}
              </Stack>
            ),
          },
          // Telefon jadvalda emas — kartada (qidiruv uni baribir topadi):
          // 1440 px da jadval gorizontal surilmasligi kerak.
          { field: 'last_login_at', headerName: 'Oxirgi kirish', width: 125, renderCell: LastSeenCell },
          {
            field: 'is_active', headerName: 'Holat', width: 105,
            exportValue: (value) => (value ? 'Faol' : 'Bloklangan'),
            renderCell: (params) => (
              <Chip
                size="small"
                color={params.value ? 'success' : 'error'}
                variant={params.value ? 'filled' : 'outlined'}
                label={params.value ? 'Faol' : 'Bloklangan'}
              />
            ),
          },
        ]}
        filters={[
          { name: 'role', label: 'Rol', type: 'select', options: roleOptions },
          // Viloyat xodimi faqat o'z viloyatini ko'radi — tanlov ma'nosiz.
          { name: 'region', label: 'Viloyat', type: 'select', options: regionOptions, regionScope: true },
          {
            name: 'is_active', label: 'Holat', type: 'select',
            options: [{ value: 'true', label: 'Faol' }, { value: 'false', label: 'Bloklangan' }],
          },
        ]}
        rowActions={(row) => (
          <Tooltip title="Parolni tiklash">
            <IconButton size="small" onClick={() => setResetTarget(row)}>
              <KeyIcon fontSize="small" />
            </IconButton>
          </Tooltip>
        )}
        fields={fields}
        formContext={{ currentUserId: currentUser?.id }}
      />

      {detail && (
        <UserDetailDialog
          row={detail.row}
          canManage={canManage}
          onClose={() => setDetail(null)}
          onEdit={(user) => {
            setDetail(null)
            detail.openEdit(user)
          }}
          onResetPassword={(user) => setResetTarget(user)}
        />
      )}

      <ConfirmDialog
        open={Boolean(resetTarget)}
        title="Parolni tiklash"
        description={`${resetTarget?.full_name || resetTarget?.username} uchun yangi parol o‘rnatiladi.`}
        confirmLabel="Parolni o‘rnatish"
        requireReason
        reasonLabel="Yangi parol"
        reasonMinLength={8}
        loading={resetting}
        onConfirm={handleReset}
        onClose={() => setResetTarget(null)}
      />
    </>
  )
}
