import { Alert, Chip, Stack, Typography } from '@mui/material'
import ResourcePage from '../../components/data/ResourcePage'
import { riskWeights as riskWeightsApi } from '../../api/endpoints'
import { EVENT_LABEL } from '../../utils/labels'
import { CATEGORY_META, categoryOf } from '../../utils/events'

/**
 * Hodisa turlari — ro'yxat `EVENT_LABEL` dan olinadi.
 *
 * Qo'lda yozilgan ikkinchi ro'yxat albatta ajralib ketardi: yangi
 * hodisa turi qo'shilganda uni uch joyda (backend, yorliqlar, bu
 * yerda) eslash kerak bo'lardi va uchinchisi doim unutilardi.
 * Turkum bo'yicha guruhlash esa 39 ta variantli ro'yxatni
 * o'qiladigan qiladi.
 */
const EVENT_OPTIONS = Object.keys(EVENT_LABEL)
  .map((type) => ({
    value: type,
    label: `${EVENT_LABEL[type]} — ${type}`,
    category: categoryOf(type),
  }))
  .sort(
    (a, b) =>
      CATEGORY_META[a.category].order - CATEGORY_META[b.category].order ||
      a.label.localeCompare(b.label),
  )

/**
 * Hodisa og'irliklari — xavf balliga qancha qo'shilishi.
 *
 * NIMA UCHUN JADVALDA, KODDA EMAS. Og'irliklar aynan ekspluatatsiya
 * davomida sozlanadi: birinchi imtihon mavsumidan keyin ma'lum
 * bo'ladiki, masalan `window_blur` juda tez-tez uchraydi va uning
 * og'irligi haqiqiy buzilishlarni ko'mib yuboryapti. Buni tuzatish
 * uchun reliz kutish kerak bo'lmasligi kerak.
 *
 * JADVAL BO'SH BO'LSA tizim ishlashdan TO'XTAMAYDI — koddagi
 * qiymatlar (`ingest.RISK_WEIGHTS`) zaxira sifatida qoladi. Bu
 * yerdagi qator esa o'shani BEKOR QILADI.
 *
 * JIDDIYLIK BU YERDA YO'Q. Uni client beradi (kontekstni u ko'radi)
 * va u darhol yozish, proktor ekrani va dalil yig'ishni hal qiladi.
 * Ilgari ustun bor edi, lekin hech qayerda o'qilmasdi — administrator
 * uni o'zgartirib, hech narsa o'zgarmaganini ko'rardi.
 */
export default function RiskWeightsPage() {
  return (
    <ResourcePage
      // Barcha viloyatlar uchun bitta yozuv — o'zgartirish respublika darajasida.
      shared
      title="Hodisa og‘irliklari"
      subtitle="Har bir hodisa turi xavf balliga qancha qo‘shadi"
      queryKey="risk-weights"
      api={riskWeightsApi}
      permission="controls.proctoring_manage"
      searchPlaceholder="Hodisa turi bo‘yicha…"
      defaultSort={{ field: 'weight', sort: 'desc' }}
      defaults={{ weight: 5, cooldown_s: 0, is_active: true }}
      getRowLabel={(row) => EVENT_LABEL[row?.event_type] || row?.event_type}
      deleteDescription={
        'Qator o‘chirilsa bu tur uchun KODDAGI standart og‘irlik qaytadi — ' +
        'hodisa ballga qo‘shilishdan to‘xtamaydi.'
      }
      banner={
        <Alert severity="info" variant="outlined">
          Bu yerda sanalmagan turlar koddagi standart og‘irlik bilan hisoblanadi.
          Ball 0–100 oralig‘ida qirqiladi va vaqt o‘tishi bilan pasayadi —
          pasayish tezligi <b>Kuzatuv siyosati</b>da. «Takror oralig‘i» ichida
          qayta kelgan bir xil hodisa yoziladi, lekin ballga qo‘shilmaydi;
          0 bo‘lsa siyosatdagi umumiy oraliq ishlaydi.
        </Alert>
      }
      columns={[
        {
          field: 'event_type', headerName: 'Hodisa', flex: 1, minWidth: 260,
          renderCell: (params) => {
            const meta = CATEGORY_META[categoryOf(params.value)]
            return (
              <Stack direction="row" spacing={0.75} alignItems="center">
                <Chip size="small" variant="outlined" color={meta.color} label={meta.label} />
                <Typography variant="body2">
                  {EVENT_LABEL[params.value] || params.value}
                </Typography>
              </Stack>
            )
          },
          exportValue: (value) => `${EVENT_LABEL[value] || value} (${value})`,
        },
        {
          field: 'weight', headerName: 'Og‘irlik', width: 120, type: 'number',
          renderCell: (params) => (
            <Typography variant="body2" fontWeight={600}>+{params.value}</Typography>
          ),
        },
        {
          field: 'cooldown_s', headerName: 'Takror oralig‘i', width: 150, type: 'number',
          exportValue: (value) => (value ? `${value} s` : 'siyosatdagi qiymat'),
          renderCell: (params) =>
            params.value > 0 ? (
              <Typography variant="body2">{params.value} s</Typography>
            ) : (
              <Typography variant="body2" color="text.disabled">siyosatdagi</Typography>
            ),
        },
      ]}
      toggleField="is_active"
      exportName="hodisa-ogirliklari"
      filters={[
        {
          name: 'is_active', label: 'Holat', type: 'select',
          options: [{ value: 'true', label: 'Faol' }, { value: 'false', label: 'Nofaol' }],
        },
      ]}
      fields={[
        {
          name: 'event_type', label: 'Hodisa turi', type: 'select', required: true,
          options: EVENT_OPTIONS, colSpan: 12,
          helperText: 'Har bir tur uchun bitta qator',
        },
        {
          name: 'weight', label: 'Og‘irlik', type: 'number', required: true,
          min: 0, max: 100, integer: true, colSpan: 6,
          helperText: '0 — ballga qo‘shilmaydi (hodisa baribir yoziladi)',
        },
        {
          name: 'cooldown_s', label: 'Takror oralig‘i (s)', type: 'number', required: true,
          min: 0, max: 3600, integer: true, colSpan: 6,
          // Shovqinli turlarga (oynadan chiqish, chetga qarash) uzun,
          // kam va jiddiylariga (telefon, ikkinchi odam) qisqa oraliq.
          helperText: '0 — siyosatdagi umumiy qiymat; boshqa son uni shu tur uchun almashtiradi',
        },
        { name: 'is_active', label: 'Faol', type: 'boolean', colSpan: 12 },
      ]}
    />
  )
}
