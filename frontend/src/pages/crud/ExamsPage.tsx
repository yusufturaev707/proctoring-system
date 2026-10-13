import { Chip, Typography } from '@mui/material'
import ResourcePage from '../../components/data/ResourcePage'
import { countCell, useExamTypeOptions, useSettingOptions } from './shared'
import { exams as examsApi } from '../../api/endpoints'

export default function ExamsPage() {
  const { options: settingOptions } = useSettingOptions()
  const { options: examTypeOptions } = useExamTypeOptions()

  return (
    <ResourcePage
      // Barcha viloyatlar uchun bitta yozuv — o'zgartirish respublika darajasida.
      shared
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
          // Sarlavhaning O'ZI hech qachon serverdan kelmaydi — faqat
          // niqob (`Authorization: Bear••••••434u`). Ustunning vazifasi
          // bitta savolga javob berish: shu imtihonda platforma tokeni
          // sozlanganmi? Sozlanmagan bo'lsa WebView 401 bilan ochiladi
          // va sabab faqat shu yerdan ko'rinadi.
          field: 'site_header_masked', headerName: 'Platforma sarlavhasi', flex: 1.2,
          minWidth: 210, sortable: false,
          exportValue: (value) => value || 'O‘rnatilmagan',
          renderCell: (params) => (
            params.value
              ? (
                <Typography
                  variant="body2"
                  sx={{ fontFamily: 'monospace', fontSize: 12.5 }}
                  noWrap
                  title={params.value}
                >
                  {params.value}
                </Typography>
              )
              : <Chip size="small" variant="outlined" color="warning" label="O‘rnatilmagan" />
          ),
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
          name: 'site_url', label: 'Tekshiruv API manzili', required: true,
          pattern: 'url', maxLength: 500, colSpan: 12, section: 'Test platformasi',
          // BU MANZILNI SERVER CHAQIRADI, client emas: JSHSHIR
          // kiritilganda backend shu manzilga `?imie=<jshshir>` bilan
          // GET yuboradi va javobdagi `test_link` ni oladi. WebView
          // esa aynan o'sha havolani ochadi — ya'ni bu maydon
          // "test sahifasi" emas, "tekshiruv endpointi".
          helperText:
            'Server shu manzilga ?imie=<JSHSHIR> bilan GET yuboradi. Test sahifasi javobdagi test_link’dan ochiladi',
        },
        {
          name: 'site_header', label: 'Platforma sarlavhasi', type: 'password',
          maxLength: 4096, colSpan: 12, section: 'Test platformasi',
          // Server sarlavhani HECH QACHON qaytarmaydi — faqat niqob
          // (`site_header_masked`). Bo'sh qoldirilsa mavjud qiymat
          // o'zgarmaydi (`clearable: false`).
          helperText: (isEdit) =>
            isEdit
              ? 'Bo‘sh qoldirilsa — sarlavha o‘zgarmaydi. Namuna: Authorization: Bearer <token>'
              : 'To‘liq ko‘rinishda: Authorization: Bearer <token>. Shifrlangan saqlanadi va faqat serverda ishlatiladi',
          clearable: false,
          validate: (value) => {
            const raw = (value || '').trim()
            if (!raw) return null
            if (/[\r\n]/.test(raw)) return 'Sarlavha bitta qatordan iborat bo‘lishi kerak'
            const index = raw.indexOf(':')
            if (index <= 0 || !raw.slice(index + 1).trim()) {
              return 'Format: Authorization: Bearer <token>'
            }
            return null
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
