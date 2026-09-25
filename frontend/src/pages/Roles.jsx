import { useCallback, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Box, Card, CardContent, Checkbox, Chip, Divider, FormControlLabel, Grid,
  Stack, Typography,
} from '@mui/material'
import KeyIcon from '@mui/icons-material/VpnKeyOutlined'

import ResourcePage from '../components/data/ResourcePage'
import { permissions as permissionsApi, roles as rolesApi } from '../api/endpoints'

const GROUP_LABEL = {
  dashboard: 'Boshqaruv paneli',
  sessions: 'Sessiyalar',
  technical: 'Texnik muammolar',
  users: 'Foydalanuvchilar',
  devices: 'Qurilmalar',
  regions: 'Hududlar',
  exams: 'Imtihonlar',
  controls: 'Sozlamalar',
  audit: 'Audit',
  client: 'Desktop client',
}

export default function Roles() {
  // `PermissionViewSet` da `pagination_class = None` — javob xom massiv.
  const { data: permissionsData } = useQuery({
    queryKey: ['permissions'],
    queryFn: () => permissionsApi.list(),
    staleTime: 10 * 60 * 1000,
  })

  const grouped = useMemo(() => {
    const list = Array.isArray(permissionsData) ? permissionsData : (permissionsData?.results || [])
    return list.reduce((acc, item) => {
      ;(acc[item.group] ||= []).push(item)
      return acc
    }, {})
  }, [permissionsData])

  const renderMatrix = useCallback(
    ({ value, onChange, disabled }) => (
      <PermissionMatrix
        grouped={grouped}
        selected={Array.isArray(value) ? value : []}
        onChange={onChange}
        disabled={disabled}
      />
    ),
    [grouped],
  )

  return (
    <ResourcePage
      // Barcha viloyatlar uchun bitta yozuv — o'zgartirish respublika darajasida.
      shared
      title="Rollar va ruxsatlar"
      subtitle="Har bir rol uchun aniq amallar to‘plami"
      queryKey="roles"
      api={rolesApi}
      permission="users.manage"
      searchPlaceholder="Rol nomi bo‘yicha…"
      defaultSort={{ field: 'key', sort: 'asc' }}
      defaults={{ is_active: true, is_global: false, permission_ids: [] }}
      getRowLabel={(row) => row?.name}
      formMaxWidth="lg"
      exportName="rollar"
      height={560}
      // Rolni o'chirish unga biriktirilgan xodimlarni ruxsatsiz qoldiradi.
      // Nomni qo'lda yozdirish — tasodifiy bosishning oldini oladi.
      deleteConfirmPhrase
      deleteDescription="Bu rolga biriktirilgan xodimlar barcha ruxsatlarini yo‘qotadi. Avval ularga boshqa rol bering."
      toggleField="is_active"
      columns={[
        { field: 'key', headerName: 'Kalit', width: 90 },
        { field: 'name', headerName: 'Rol', flex: 1, minWidth: 170 },
        { field: 'description', headerName: 'Izoh', flex: 1.5, minWidth: 210, sortable: false },
        {
          field: 'permissions', headerName: 'Ruxsatlar', width: 130, sortable: false,
          // Eksportda chip emas, son chiqishi kerak.
          valueGetter: (value) => value?.length || 0,
          renderCell: (params) => (
            <Chip size="small" icon={<KeyIcon />} label={params.value} variant="outlined" />
          ),
        },
        {
          field: 'is_global', headerName: 'Qamrov', width: 135, sortable: false,
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
          field: 'users_count', headerName: 'Xodimlar', width: 110, sortable: false,
          align: 'right', headerAlign: 'right',
          renderCell: (params) =>
            params.value > 0
              ? <Typography variant="body2" fontWeight={600}>{params.value}</Typography>
              : <Typography variant="body2" color="text.disabled">—</Typography>,
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
        { name: 'name', label: 'Rol nomi', required: true, maxLength: 150, colSpan: 8 },
        {
          name: 'key', label: 'Kalit', type: 'number', required: true,
          min: 0, max: 32767, integer: true, colSpan: 4,
          helperText: 'Raqamli identifikator — tizim bo‘ylab unikal',
        },
        { name: 'description', label: 'Izoh', maxLength: 500, colSpan: 12 },
        { name: 'is_active', label: 'Faol', type: 'boolean', colSpan: 6 },
        {
          name: 'is_global', label: 'Butun respublika bo‘yicha', type: 'boolean', colSpan: 6,
          helperText:
            'Yoqilsa — bu roldagi xodim BARCHA viloyatlarni ko‘radi va unga viloyat ' +
            'biriktirish shart emas. O‘chirilgan bo‘lsa, xodim faqat o‘z viloyati ' +
            'ma’lumotini ko‘radi.',
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
      formDescription="Ruxsatlar to‘plami darhol kuchga kiradi — foydalanuvchi keyingi so‘rovida yangi huquqlar bilan ishlaydi."
    />
  )
}

function PermissionMatrix({ grouped, selected, onChange, disabled }) {
  const toggleOne = (id) =>
    onChange(selected.includes(id) ? selected.filter((item) => item !== id) : [...selected, id])

  const toggleGroup = (items) => {
    const ids = items.map((item) => item.id)
    const allSelected = ids.every((id) => selected.includes(id))
    onChange(
      allSelected
        ? selected.filter((id) => !ids.includes(id))
        : [...new Set([...selected, ...ids])],
    )
  }

  const groups = Object.entries(grouped)

  if (!groups.length) {
    return (
      <Typography variant="body2" color="text.secondary">
        Ruxsatlar ro‘yxati yuklanmoqda…
      </Typography>
    )
  }

  return (
    <Box>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
        {selected.length} ta ruxsat tanlangan
      </Typography>

      <Grid container spacing={2}>
        {groups.map(([group, items]) => {
          const ids = items.map((item) => item.id)
          const chosen = ids.filter((id) => selected.includes(id)).length
          const all = chosen === ids.length
          return (
            <Grid item xs={12} sm={6} md={4} key={group}>
              <Card
                variant="outlined"
                sx={{
                  height: '100%',
                  // Tanlangan guruh chetidan urg'u — uzun ro'yxatda
                  // qaysi bo'lim to'liq yoqilganini bir qarashda ko'rsatadi.
                  borderColor: chosen ? 'primary.main' : 'divider',
                }}
              >
                <CardContent sx={{ p: 1.5, '&:last-child': { pb: 1.5 } }}>
                  <Stack direction="row" alignItems="center" justifyContent="space-between">
                    <Box sx={{ minWidth: 0 }}>
                      <Typography variant="subtitle2" noWrap>
                        {GROUP_LABEL[group] || group}
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        {chosen} / {ids.length}
                      </Typography>
                    </Box>
                    <Checkbox
                      size="small"
                      checked={all}
                      indeterminate={chosen > 0 && !all}
                      disabled={disabled}
                      onChange={() => toggleGroup(items)}
                      inputProps={{ 'aria-label': `${GROUP_LABEL[group] || group} — barchasi` }}
                    />
                  </Stack>
                  <Divider sx={{ my: 0.5 }} />
                  {items.map((item) => (
                    <FormControlLabel
                      key={item.id}
                      sx={{ display: 'flex', ml: 0 }}
                      control={
                        <Checkbox
                          size="small"
                          checked={selected.includes(item.id)}
                          disabled={disabled}
                          onChange={() => toggleOne(item.id)}
                        />
                      }
                      label={<Typography variant="body2">{item.name}</Typography>}
                    />
                  ))}
                </CardContent>
              </Card>
            </Grid>
          )
        })}
      </Grid>
    </Box>
  )
}
