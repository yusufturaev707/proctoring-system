import { Chip, Stack, Typography } from '@mui/material'
import ResourcePage from '../../components/data/ResourcePage'
import { rdpObjects as rdpObjectsApi } from '../../api/endpoints'

/**
 * Masofaviy boshqaruv dasturlari (AnyDesk, TeamViewer, RustDesk...).
 *
 * Client `process_names` ro'yxatidagi jarayonlarni qidiradi va topsa
 * `rdp_detected` hodisasini yaratadi. Ro'yxat serverda turadi, ya'ni
 * yangi dastur paydo bo'lsa client'ni qayta yig'ish shart emas.
 */
export default function RdpObjectsPage() {
  return (
    <ResourcePage
      title="RDP dasturlar"
      subtitle="Masofaviy boshqaruv dasturlarini aniqlash ro‘yxati"
      queryKey="rdp-objects"
      api={rdpObjectsApi}
      permission="controls.manage"
      searchPlaceholder="Nomi yoki kodi bo‘yicha…"
      defaultSort={{ field: 'name', sort: 'asc' }}
      defaults={{ is_active: true, process_names: [] }}
      getRowLabel={(row) => row?.name}
      deleteDescription="Dastur o‘chirilsa, client uni endi aniqlamaydi."
      columns={[
        { field: 'name', headerName: 'Nomi', flex: 1, minWidth: 170 },
        { field: 'code', headerName: 'Kod', width: 150 },
        {
          field: 'process_names', headerName: 'Jarayonlar', flex: 1.6, minWidth: 220,
          sortable: false,
          exportValue: (value) => (value || []).join(', '),
          renderCell: (params) => {
            const items = params.value || []
            if (!items.length) {
              return <Typography variant="body2" color="error.main">Ko‘rsatilmagan</Typography>
            }
            return (
              <Stack direction="row" spacing={0.5} sx={{ overflow: 'hidden' }}>
                {/* Kalit indeks bo'yicha: ro'yxat erkin kiritiladi va
                    takroriy nom bo'lishi mumkin. */}
                {items.slice(0, 3).map((item, index) => (
                  <Chip key={index} size="small" variant="outlined" label={item} />
                ))}
                {items.length > 3 && <Chip size="small" label={`+${items.length - 3}`} />}
              </Stack>
            )
          },
        },
      ]}
      toggleField="is_active"
      exportName="rdp-dasturlar"
      filters={[
        {
          name: 'is_active', label: 'Holat', type: 'select',
          options: [{ value: 'true', label: 'Faol' }, { value: 'false', label: 'Nofaol' }],
        },
      ]}
      fields={[
        { name: 'name', label: 'Nomi', required: true, maxLength: 100, colSpan: 6 },
        {
          name: 'code', label: 'Kod', required: true, maxLength: 100, colSpan: 6,
          transform: (value) => String(value || '').trim().toLowerCase(),
          helperText: 'Barqaror kalit — keyin o‘zgartirilmasligi kerak',
        },
        {
          name: 'process_names', label: 'Jarayon nomlari (JSON massiv)', type: 'json',
          colSpan: 12, emptyValue: [],
          helperText:
            'Masalan: ["AnyDesk.exe", "AnyDeskService.exe"]. Client aynan shu nomlarni qidiradi.',
          validate: (value) => {
            if (!value?.trim()) return null
            try {
              const parsed = JSON.parse(value)
              if (!Array.isArray(parsed)) return 'Massiv bo‘lishi kerak: ["App.exe"]'
              if (parsed.some((item) => typeof item !== 'string' || !item.trim())) {
                return 'Har bir element bo‘sh bo‘lmagan matn bo‘lishi kerak'
              }
              return null
            } catch {
              return 'JSON formati noto‘g‘ri'
            }
          },
        },
        { name: 'is_active', label: 'Faol', type: 'boolean', colSpan: 12 },
      ]}
    />
  )
}
