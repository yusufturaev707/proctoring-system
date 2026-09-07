import { Chip, Stack, Typography } from '@mui/material'
import ResourcePage from '../../components/data/ResourcePage'
import { countCell, useExamTypeOptions, useSettingOptions } from './shared'
import { exams as examsApi } from '../../api/endpoints'

export default function ExamsPage() {
  const { options: settingOptions } = useSettingOptions()
  const { options: examTypeOptions } = useExamTypeOptions()

  return (
    <ResourcePage
      title="Imtihonlar"
      subtitle="Tashqi test platformasidagi testlar bilan bog‘lanish"
      queryKey="exams"
      restorable
      api={examsApi}
      permission="exams.manage"
      searchPlaceholder="Nomi, kalit yoki tashqi kod…"
      defaultSort={{ field: 'name', sort: 'asc' }}
      defaults={{
        is_active: true,
        site_url: 'https://ntest.uzbmb.uz/login',
        duration_minutes: 180,
      }}
      getRowLabel={(row) => row?.name}
      deleteConfirmPhrase
      deleteDescription="Imtihonga bog‘langan sessiyalar mavjud bo‘lsa, server o‘chirishga ruxsat bermaydi."
      formMaxWidth="md"
      columns={[
        { field: 'name', headerName: 'Nomi', flex: 1.5, minWidth: 190 },
        {
          field: 'exam_type_name', headerName: 'Turi', width: 155, sortable: false,
          renderCell: (params) => (
            params.value
              ? <Typography variant="body2">{params.value}</Typography>
              : <Typography variant="body2" color="text.disabled">Belgilanmagan</Typography>
          ),
        },
        { field: 'key', headerName: 'Kalit', width: 140 },
        { field: 'external_code', headerName: 'Tashqi kod', width: 150 },
        {
          field: 'duration_minutes', headerName: 'Davomiylik', width: 125,
          renderCell: (params) => (
            <Typography variant="body2">
              {Math.floor(params.value / 60)}s {params.value % 60 ? `${params.value % 60}d` : ''}
            </Typography>
          ),
        },
        {
          field: 'allowed_domains', headerName: 'Ruxsat etilgan domenlar', flex: 1.2,
          minWidth: 200, sortable: false,
          exportValue: (value) => (value || []).join(', '),
          renderCell: (params) => {
            const domains = params.value || []
            if (!domains.length) {
              return <Typography variant="body2" color="text.disabled">site_url domeni</Typography>
            }
            return (
              <Stack direction="row" spacing={0.5} sx={{ overflow: 'hidden' }}>
                {/* Kalit indeks bo'yicha: `allowed_domains` — erkin
                    kiritiladigan ro'yxat va unda takroriy domen bo'lishi
                    mumkin. Domenning o'zini kalit qilish React'da
                    "duplicate key" ogohlantirishini beradi va chiplarni
                    tushirib qoldirishi mumkin. */}
                {domains.slice(0, 2).map((domain, index) => (
                  <Chip key={index} size="small" variant="outlined" label={domain} />
                ))}
                {domains.length > 2 && <Chip size="small" label={`+${domains.length - 2}`} />}
              </Stack>
            )
          },
        },
        {
          field: 'sessions_count', headerName: 'Sessiya', width: 105, sortable: false,
          align: 'right', headerAlign: 'right', renderCell: countCell,
        },
        {
          field: 'setting_name', headerName: 'Sozlama', width: 160, sortable: false,
          renderCell: (params) => (
            params.value
              ? <Typography variant="body2">{params.value}</Typography>
              : <Typography variant="body2" color="text.disabled">Global standart</Typography>
          ),
        },
      ]}
      toggleField="is_active"
      exportName="imtihonlar"
      filters={[
        { name: 'exam_type', label: 'Turi', type: 'select', options: examTypeOptions },
        {
          name: 'is_active', label: 'Holat', type: 'select',
          options: [{ value: 'true', label: 'Faol' }, { value: 'false', label: 'Nofaol' }],
        },
      ]}
      fields={[
        { name: 'name', label: 'Nomi', required: true, maxLength: 255, colSpan: 12 },
        {
          name: 'exam_type', label: 'Imtihon turi', type: 'select',
          options: examTypeOptions, colSpan: 12,
          helperText: 'Bo‘sh qoldirilsa — tur belgilanmagan holida qoladi',
        },
        { name: 'key', label: 'Ichki kalit', maxLength: 100, colSpan: 6 },
        {
          name: 'external_code', label: 'Tashqi platforma kodi', maxLength: 100, colSpan: 6,
          helperText: 'ntest tizimidagi imtihon identifikatori',
        },
        {
          name: 'site_url', label: 'Test platformasi URL', required: true,
          pattern: 'url', maxLength: 500, colSpan: 12, section: 'WebView',
        },
        {
          name: 'allowed_domains', label: 'Ruxsat etilgan domenlar (JSON massiv)',
          type: 'json', colSpan: 12, section: 'WebView', emptyValue: [],
          helperText:
            'Masalan: ["ntest.uzbmb.uz"]. Client shu ro‘yxatni WebView allowlist sifatida ishlatadi — ' +
            'boshqa saytlar bloklanadi. Bo‘sh qoldirilsa site_url domeni olinadi.',
          validate: (value) => {
            if (!value?.trim()) return null
            try {
              const parsed = JSON.parse(value)
              if (!Array.isArray(parsed)) return 'Massiv bo‘lishi kerak: ["domain.uz"]'
              if (parsed.some((item) => typeof item !== 'string' || !item.trim())) {
                return 'Har bir element bo‘sh bo‘lmagan matn bo‘lishi kerak'
              }
              return null
            } catch {
              return 'JSON formati noto‘g‘ri'
            }
          },
        },
        {
          name: 'duration_minutes', label: 'Davomiyligi (daqiqa)', type: 'number',
          required: true, min: 5, max: 600, integer: true, colSpan: 6, section: 'Sozlamalar',
        },
        { name: 'is_active', label: 'Faol', type: 'boolean', colSpan: 6, section: 'Sozlamalar' },
        {
          name: 'setting', label: 'Proktorlik profili', type: 'select',
          options: settingOptions, colSpan: 12, section: 'Sozlamalar',
          helperText:
            'Shu imtihon uchun FaceID chegaralari, skrinshot intervali va taqiqlangan ' +
            'obyektlar. Bo‘sh qoldirilsa global standart qo‘llanadi.',
        },
      ]}
    />
  )
}
