import { useState } from 'react'
import { Chip, IconButton, Stack, Tooltip, Typography } from '@mui/material'
import KeyIcon from '@mui/icons-material/VpnKeyOutlined'

import ResourcePage from '../components/data/ResourcePage'
import ConfirmDialog from '../components/ConfirmDialog'
import { LastSeenCell, useRegionOptions, useRoleOptions } from './crud/shared'
import { users as usersApi } from '../api/endpoints'
import { useAuth } from '../context/AuthContext'
import { useUi } from '../context/UiContext'

export default function Users() {
  const { user: currentUser } = useAuth()
  const { notify, notifyError } = useUi()
  const { options: roleOptions } = useRoleOptions()
  const { options: regionOptions } = useRegionOptions()

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

  return (
    <>
      <ResourcePage
        title="Foydalanuvchilar"
        subtitle="Adminlar, proktorlar va monitoring xodimlari"
        queryKey="users"
        api={usersApi}
        permission="users.manage"
        searchPlaceholder="Login, F.I.Sh. yoki telefon…"
        defaultSort={{ field: 'username', sort: 'asc' }}
        defaults={{ is_active: true }}
        getRowLabel={(row) => row?.username}
        deleteConfirmPhrase
        deleteDescription="Foydalanuvchi o‘chirilsa, uning audit yozuvlari saqlanib qoladi (muallif nomi bilan)."
        formMaxWidth="md"
        columns={[
          { field: 'username', headerName: 'Login', width: 160 },
          { field: 'full_name', headerName: 'F.I.Sh.', flex: 1.5, minWidth: 200, sortable: false },
          { field: 'phone', headerName: 'Telefon', width: 150, sortable: false },
          {
            field: 'role_name', headerName: 'Rol', width: 175, sortable: false,
            exportValue: (value, row) => (row.is_superuser ? 'Superuser' : value || ''),
            // Superuser hisob rol tekshiruvidan ham, viloyat filtridan ham
            // O'TADI (`HasRolePermission`, `User.is_region_scoped`).
            // Ilgari bunday hisob ro'yxatda "Biriktirilmagan" bo'lib
            // ko'rinardi, ya'ni eng ko'p huquqli hisob eng huquqsizdek
            // tuyulardi. Endi u alohida belgilanadi.
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
                : <Typography variant="body2" color="error.main">Biriktirilmagan</Typography>
            },
          },
          {
            field: 'region_name', headerName: 'Viloyat', flex: 1, minWidth: 150, sortable: false,
            renderCell: (params) =>
              params.value || <Typography variant="body2" color="text.secondary">Barchasi</Typography>,
            exportValue: (value) => value || 'Barchasi',
          },
          { field: 'last_login_at', headerName: 'Oxirgi kirish', width: 150, renderCell: LastSeenCell },
          {
            field: 'is_active', headerName: 'Holat', width: 125,
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
        fields={[
          {
            name: 'username', label: 'Login', required: true, maxLength: 150,
            pattern: 'slug', colSpan: 6, autoComplete: 'off',
            // Login o'zgarishi audit izini uzadi va foydalanuvchini
            // chalkashtiradi — yaratilgandan keyin o'zgartirilmaydi.
            disabled: (_form, isEdit) => isEdit,
            helperText: (isEdit) =>
              isEdit ? 'Login o‘zgartirilmaydi' : 'Faqat harf, raqam, `-` va `_`',
          },
          {
            name: 'password', label: 'Parol', type: 'password', minLength: 3,
            colSpan: 6, password: true, clearable: false,
            helperText: (isEdit) =>
              isEdit ? 'Bo‘sh qoldirilsa — o‘zgarmaydi' : 'Kamida 8 ta belgi',
            validate: (value, form) => {
              // Yangi foydalanuvchi uchun parol majburiy, tahrirlashda esa
              // bo'sh bo'lishi kerak — shuning uchun `required` emas,
              // kontekstga bog'liq tekshiruv.
              if (!form._meta?.isEdit && !value) return 'Yangi foydalanuvchi uchun parol shart'
              return null
            },
          },
          { name: 'last_name', label: 'Familiya', maxLength: 255, colSpan: 4, section: 'Shaxsiy' },
          { name: 'first_name', label: 'Ism', maxLength: 255, colSpan: 4, section: 'Shaxsiy' },
          { name: 'middle_name', label: 'Otasining ismi', maxLength: 255, colSpan: 4, section: 'Shaxsiy' },
          {
            name: 'phone', label: 'Telefon', maxLength: 20, colSpan: 6, section: 'Shaxsiy',
            pattern: { re: /^[+\d\s()-]{7,20}$/, message: 'Telefon formati noto‘g‘ri' },
          },
          {
            name: 'telegram_id', label: 'Telegram ID', maxLength: 32, colSpan: 6, section: 'Shaxsiy',
          },
          {
            name: 'role', label: 'Rol', type: 'select', options: roleOptions,
            colSpan: 6, section: 'Huquqlar',
            helperText: 'Rol foydalanuvchining barcha ruxsatlarini belgilaydi',
          },
          {
            name: 'region', label: 'Viloyat', type: 'select', options: regionOptions,
            colSpan: 6, section: 'Huquqlar',
            helperText: 'Bo‘sh — barcha viloyatlarni ko‘radi',
          },
          {
            name: 'is_active', label: 'Faol', type: 'boolean', colSpan: 6, section: 'Huquqlar',
            // O'zini bloklab qo'yish — qaytarib bo'lmaydigan xato:
            // foydalanuvchi tizimdan chiqib ketadi va qayta kira olmaydi.
            disabled: (form) => form._meta?.row?.id === form._meta?.currentUserId,
            helperText: (isEdit) => (isEdit ? 'O‘z hisobingizni bloklay olmaysiz' : ''),
          },
          {
            name: 'is_staff', label: 'Django admin panelga kirish', type: 'boolean',
            colSpan: 6, section: 'Huquqlar',
            helperText: 'Faqat texnik xodimlar uchun — /admin/ paneliga kirish huquqi',
          },
        ]}
        formContext={{ currentUserId: currentUser?.id }}
      />

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
