import { useState } from 'react'
import { Box, Chip, Stack, Typography } from '@mui/material'
import SchoolIcon from '@mui/icons-material/SchoolOutlined'
import LabelIcon from '@mui/icons-material/LabelOutlined'
import LinkIcon from '@mui/icons-material/LinkOutlined'
import TuneIcon from '@mui/icons-material/TuneOutlined'
import KeyIcon from '@mui/icons-material/VpnKeyOutlined'

import ResourcePage from '../../components/data/ResourcePage'
import ChipListInput from '../../components/controls/ChipListInput'
import type { CellParams, CustomFieldProps, RowDetail } from '../../components/data/types'
import ExamDetailDialog from '../../components/exams/ExamDetailDialog'
import { durationText } from '../../components/exams/examText'
import { countCell, useExamTypeOptions, useSettingOptions } from './shared'
import { exams as examsApi } from '../../api/endpoints'
import { useAuth } from '../../context/AuthContext'

// Maxsus `renderCell` DataGrid'ning oddiy kataklaridek o'zi tekislanmaydi.
const cell = { height: '100%', display: 'flex', alignItems: 'center', minWidth: 0 }
// Nom + tur, kalit + tashqi kod — ikki qator. Modul doimiysi: `DataGrid`
// props barqaror bo'lishi kerak.
const examRowHeight = () => 52
// `countCell` o'zi tekislanmaydi — o'ngga va vertikal markazga (`ZonesPage` bilan bir xil).
const rightCount = (params: CellParams<number | null>) => (
  <Box sx={{ ...cell, justifyContent: 'flex-end' }}>{countCell(params)}</Box>
)

const FORM_SECTIONS = {
  'Asosiy': { icon: LabelIcon, description: 'Nom va tur ro‘yxatlarda ko‘rinadi, kodlar hisobot va integratsiyada ishlatiladi' },
  'Test platformasi': {
    icon: LinkIcon,
    description: 'Server JSHSHIR’ni shu manzil orqali tekshiradi — client platformaga o‘zi murojaat qilmaydi',
  },
  'Sozlamalar': { icon: TuneIcon, description: 'Test vaqti va proktorlik profili (FaceID, skrinshot, bron rejimi)' },
}

export default function ExamsPage() {
  const { options: settingOptions } = useSettingOptions()
  const { options: examTypeOptions } = useExamTypeOptions()
  const { canShared } = useAuth()
  const canManage = canShared('exams.manage')
  // Qator bosilganda — imtihonning to'liq kartasi; «Tahrirlash» sahifaning
  // o'z formasini ochadi (`openEdit`), ikkinchi forma yasalmaydi.
  const [detail, setDetail] = useState<RowDetail | null>(null)

  return (
    <>
    <ResourcePage
      // Barcha viloyatlar uchun bitta yozuv — o'zgartirish respublika darajasida.
      shared
      title="Imtihonlar"
      subtitle="Tashqi test platformasidagi testlar bilan bog‘lanish. Qatorni bosing, to‘liq karta ochiladi"
      queryKey="exams"
      restorable
      api={examsApi}
      permission="exams.manage"
      searchPlaceholder="Nomi, kalit yoki tashqi kod…"
      defaultSort={{ field: 'name', sort: 'asc' }}
      defaults={{
        is_active: true,
        site_url: 'https://ntest.uzbmb.uz/login',
        resource_domains: [],
        duration_minutes: 180,
      }}
      getRowLabel={(row) => row?.name}
      deleteConfirmPhrase
      deleteDescription="Imtihonga bog‘langan sessiyalar mavjud bo‘lsa, server o‘chirishga ruxsat bermaydi."
      formMaxWidth="md"
      getRowHeight={examRowHeight}
      formIcon={<SchoolIcon />}
      formTitle={(isEdit, row) => (isEdit ? `${row?.name} — tahrirlash` : 'Yangi imtihon')}
      formSections={FORM_SECTIONS}
      onRowClick={(params, { openEdit }) => setDetail({ row: params.row, openEdit })}
      columns={[
        {
          // Tur nom ostida (ikkinchi qator): alohida ustun bilan jadval
          // 1440 px ekranda gorizontal surilardi.
          field: 'name', headerName: 'Nomi', flex: 1.5, minWidth: 190,
          exportValue: (value, row) => (row.exam_type_name ? `${value} (${row.exam_type_name})` : value),
          renderCell: (params) => (
            <Stack sx={{ height: '100%', justifyContent: 'center', minWidth: 0 }}>
              <Stack direction="row" spacing={1} alignItems="center" sx={{ minWidth: 0 }}>
                <Typography variant="body2" fontWeight={600} noWrap sx={{ lineHeight: 1.35 }}>{params.value}</Typography>
                {params.row.deleted_at && <Chip size="small" color="error" variant="outlined" label="O‘chirilgan" />}
              </Stack>
              <Typography
                variant="caption"
                color={params.row.exam_type_name ? 'text.secondary' : 'text.disabled'}
                noWrap
                sx={{ lineHeight: 1.35 }}
              >
                {params.row.exam_type_name || 'Turi belgilanmagan'}
              </Typography>
            </Stack>
          ),
        },
        {
          field: 'key', headerName: 'Kalit / tashqi kod', width: 140,
          exportValue: (value, row) => [value, row.external_code].filter(Boolean).join(' / '),
          renderCell: (params) => (
            <Stack sx={{ height: '100%', justifyContent: 'center', minWidth: 0 }}>
              <Typography variant="body2" noWrap sx={{ fontFamily: 'monospace', fontSize: 12.5, lineHeight: 1.4 }}>
                {params.value || '—'}
              </Typography>
              <Typography variant="caption" color="text.secondary" noWrap sx={{ fontFamily: 'monospace', lineHeight: 1.4 }}>
                {params.row.external_code || '—'}
              </Typography>
            </Stack>
          ),
        },
        {
          field: 'duration_minutes', headerName: 'Davomiylik', width: 105,
          exportValue: (value) => durationText(value),
          renderCell: (params) => <Typography variant="body2" sx={cell}>{durationText(params.value)}</Typography>,
        },
        {
          // Sarlavhaning O'ZI hech qachon serverdan kelmaydi — faqat
          // niqob (`Authorization: Bear••••••434u`). Ustunning vazifasi
          // bitta savolga javob berish: shu imtihonda platforma tokeni
          // sozlanganmi? Sozlanmagan bo'lsa WebView 401 bilan ochiladi
          // va sabab faqat shu yerdan ko'rinadi.
          field: 'site_header_masked', headerName: 'Platforma tokeni', flex: 1,
          minWidth: 150, sortable: false,
          exportValue: (value) => value || 'O‘rnatilmagan',
          renderCell: (params) => (
            params.value
              ? (
                <Stack direction="row" spacing={0.75} alignItems="center" sx={cell} title={params.value}>
                  <KeyIcon sx={{ fontSize: 16, color: 'success.main' }} />
                  <Typography variant="body2" sx={{ fontFamily: 'monospace', fontSize: 12.5 }} noWrap>
                    {params.value}
                  </Typography>
                </Stack>
              )
              : <Chip size="small" variant="outlined" color="warning" icon={<KeyIcon />} label="O‘rnatilmagan" />
          ),
        },
        {
          field: 'sessions_count', headerName: 'Sessiya', width: 85, sortable: false,
          align: 'right', headerAlign: 'right', renderCell: rightCount,
        },
        {
          field: 'setting_name', headerName: 'Profil', width: 115, sortable: false,
          renderCell: (params) => (
            params.value
              ? <Typography variant="body2" sx={cell} noWrap>{params.value}</Typography>
              : <Typography variant="body2" color="text.disabled" sx={cell}>Global standart</Typography>
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
        { name: 'name', label: 'Nomi', required: true, maxLength: 255, colSpan: 12, section: 'Asosiy' },
        {
          name: 'exam_type', label: 'Imtihon turi', type: 'select',
          options: examTypeOptions, colSpan: 12, section: 'Asosiy',
          helperText: 'Bo‘sh qoldirilsa — tur belgilanmagan holida qoladi',
        },
        { name: 'key', label: 'Ichki kalit', maxLength: 100, colSpan: 6, section: 'Asosiy' },
        {
          name: 'external_code', label: 'Tashqi platforma kodi', maxLength: 100, colSpan: 6, section: 'Asosiy',
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
          helperText: (isEdit, form) =>
            isEdit
              ? `Hozirgisi: ${form._meta?.row?.site_header_masked || 'o‘rnatilmagan'}. Bo‘sh qoldirilsa — o‘zgarmaydi. Namuna: Authorization: Bearer <token>`
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
          // Savol rasmlari, shrift va CSS boshqa serverdan (CDN) kelsa,
          // client ularni bloklaydi — test sahifasi va API domenigina
          // ochiq. Bu ro'yxat FAQAT shunday resurslarga ochiladi:
          // talabgor bu domenga sahifa sifatida o'ta olmaydi, skript va
          // so'rovlar ham bloklanadi. Kanonik shakl va qoida serverda
          // (`apps/exams/domains.py`) — butun URL yozilsa host olinadi.
          name: 'resource_domains', type: 'custom', colSpan: 12, section: 'Test platformasi',
          render: ({ value, onChange, disabled, error }: CustomFieldProps) => (
            <ChipListInput
              value={value}
              onChange={onChange}
              disabled={disabled}
              error={error}
              label="Resurs domenlari (rasm, shrift)"
              placeholder="Masalan: cdn.uzbmb.uz — Enter bilan qo‘shing"
              helperText={
                'Savol rasmlari boshqa serverdan kelsa — shu domen. Faqat rasm, shrift, CSS va ' +
                'media uchun ochiladi; sahifa, skript va so‘rovlar bloklanadi. Qaysi domen ' +
                'bloklangani sessiya hodisalarida («URL bloklandi») ko‘rinadi'
              }
            />
          ),
        },
        {
          name: 'duration_minutes', label: 'Davomiyligi (daqiqa)', type: 'number',
          required: true, min: 5, max: 600, integer: true, colSpan: 6, section: 'Sozlamalar',
          // Platforma javobida `duration_time` kelmasa shu qiymat ishlatiladi.
          helperText: (_isEdit, form) => `${durationText(form.duration_minutes)} · platforma vaqt bermasa ishlatiladi`,
        },
        {
          name: 'setting', label: 'Proktorlik profili', type: 'select',
          options: settingOptions, colSpan: 6, section: 'Sozlamalar',
          helperText: 'Bo‘sh qoldirilsa — global standart',
        },
        {
          name: 'is_active', label: 'Faol', type: 'boolean', colSpan: 12, section: 'Sozlamalar',
          helperText: 'Nofaol imtihonni operator client dasturda tanlay olmaydi',
        },
      ]}
    />
    {detail && (
      <ExamDetailDialog
        row={detail.row}
        onClose={() => setDetail(null)}
        onEdit={canManage ? () => { setDetail(null); detail.openEdit(detail.row) } : undefined}
      />
    )}
    </>
  )
}
