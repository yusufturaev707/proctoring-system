import { useState } from 'react'
import { Chip, Stack, Typography } from '@mui/material'
import EventIcon from '@mui/icons-material/EventOutlined'
import SchoolIcon from '@mui/icons-material/SchoolOutlined'
import ScheduleIcon from '@mui/icons-material/ScheduleOutlined'
import ToggleIcon from '@mui/icons-material/ToggleOnOutlined'
import dayjs from 'dayjs'

import ResourcePage from '../../components/data/ResourcePage'
import type { RowDetail } from '../../components/data/types'
import ExamScheduleDetailDialog from '../../components/exams/ExamScheduleDetailDialog'
import { durationText, schedulePhase } from '../../components/exams/examText'
import {
  regionZoneFilters, useExamOptions, useRegionOptions, useZoneOptions, zonesOfRegion,
} from './shared'
import { examSchedules as schedulesApi } from '../../api/endpoints'
import { useAuth } from '../../context/AuthContext'
import { formatDate, formatDateTime } from '../../utils/labels'
import type { ApiRecord } from '../../types/api'

// Maxsus `renderCell` DataGrid'ning oddiy kataklaridek o'zi tekislanmaydi.
const cell = { height: '100%', display: 'flex', alignItems: 'center', minWidth: 0 }

// Modul doimiysi: `DataGrid` props barqaror bo'lishi kerak.
const scheduleRowHeight = () => 52

// Tugash boshqa kunda bo'lsa "+N" — aks holda 00:05–23:55 bir kunlik
// seansdek o'qilardi (to'liq sana kartada va CSV'da).
const timeRange = (row: ApiRecord) => {
  if (!row.starts_at || !row.ends_at) return '—'
  const start = dayjs(row.starts_at)
  const end = dayjs(row.ends_at)
  const days = end.startOf('day').diff(start.startOf('day'), 'day')
  return `${start.format('HH:mm')}–${end.format('HH:mm')}${days > 0 ? ` +${days}` : ''}`
}

const FORM_SECTIONS = {
  'Imtihon va joy': {
    icon: SchoolIcon,
    description: 'Viloyat bo‘sh — barcha binolar uchun umumiy seans (faqat respublika darajasida)',
  },
  'Vaqt': {
    icon: ScheduleIcon,
    description: 'Talabgor JSHSHIR’ni faqat kirish oynasi ochilgandan tugash vaqtigacha kirita oladi',
  },
  'Holat': { icon: ToggleIcon },
}

export default function ExamSchedulesPage() {
  const { options: examOptions } = useExamOptions()
  const { options: zoneOptions } = useZoneOptions()
  const { options: regionOptions } = useRegionOptions()
  const { user, can } = useAuth()
  // Viloyat xodimi umumiy (barcha binolar) seans yarata olmaydi — server
  // uni rad etadi (`ensure_in_region`). Formada viloyat oldindan qo'yiladi.
  const scoped = Boolean(user?.is_region_scoped)
  const [detail, setDetail] = useState<RowDetail | null>(null)
  // Umumiy seansni viloyat xodimi faqat KO'RADI (`ExamScheduleViewSet`):
  // kartadagi «Tahrirlash» server rad etadigan tugma bo'lib qolmasin.
  const canEditRow = (row: ApiRecord) => can('exams.manage') && !(scoped && !row.zone)

  return (
    <>
    <ResourcePage
      title="Imtihon jadvali"
      subtitle="Talabgor faqat ochiq kirish oynasida JSHSHIR kirita oladi. Qatorni bosing, to‘liq karta ochiladi"
      queryKey="exam-schedules"
      restorable
      api={schedulesApi}
      permission="exams.manage"
      searchable={false}
      defaultSort={{ field: 'exam_date', sort: 'desc' }}
      defaults={{
        is_active: true,
        checkin_lead_minutes: 60,
        ...(scoped ? { region: user?.region } : {}),
      }}
      getRowLabel={(row) => `${row?.exam_name} — ${row?.exam_date}`}
      formMaxWidth="md"
      // Bino + viloyat ikki qator — standart zich qatorga sig'maydi.
      getRowHeight={scheduleRowHeight}
      formIcon={<EventIcon />}
      formTitle={(isEdit, row) => (isEdit ? `${row?.exam_name} · ${formatDate(row?.exam_date)} — tahrirlash` : 'Yangi seans')}
      formSections={FORM_SECTIONS}
      onRowClick={(params, { openEdit }) => setDetail({ row: params.row, openEdit })}
      columns={[
        {
          field: 'exam_name', headerName: 'Imtihon', flex: 1.6, minWidth: 200, sortable: false,
          renderCell: (params) => (
            <Stack direction="row" spacing={1} alignItems="center" sx={cell}>
              <Typography variant="body2" fontWeight={600} noWrap>{params.value}</Typography>
              {params.row.deleted_at && <Chip size="small" color="error" variant="outlined" label="O‘chirilgan" />}
            </Stack>
          ),
        },
        {
          // Bino va viloyat bitta katakda (bino — asosiy, viloyat — ostida):
          // umumiy seansda viloyat ustuni bo'sh turib, jadvalni 1440 px da
          // gorizontal surardi.
          field: 'zone_name', headerName: 'Joy', flex: 1, minWidth: 170, sortable: false,
          exportValue: (value, row) => (value ? `${row.region_name} · ${value}` : 'Barcha binolar'),
          renderCell: (params) => (
            params.value
              ? (
                <Stack sx={{ height: '100%', justifyContent: 'center', minWidth: 0 }}>
                  <Typography variant="body2" noWrap sx={{ lineHeight: 1.3 }}>{params.value}</Typography>
                  <Typography variant="caption" color="text.secondary" noWrap sx={{ lineHeight: 1.3 }}>
                    {params.row.region_name}
                  </Typography>
                </Stack>
              )
              : <Chip size="small" variant="outlined" color="info" label="Barcha binolar" />
          ),
        },
        {
          field: 'exam_date', headerName: 'Sana', width: 110,
          valueGetter: (value: string | null) => formatDate(value),
        },
        {
          // Boshlanish va tugash bitta katakda — kun bitta (`exam_date`),
          // ikki to'liq sana-vaqt ustuni jadvalni 1440 px da surardi.
          field: 'starts_at', headerName: 'Vaqt', width: 130,
          exportValue: (_value, row) => `${formatDateTime(row.starts_at)} – ${formatDateTime(row.ends_at)}`,
          renderCell: (params) => (
            <Typography variant="body2" sx={{ ...cell, fontVariantNumeric: 'tabular-nums' }}>
              {timeRange(params.row)}
            </Typography>
          ),
        },
        {
          field: 'checkin_lead_minutes', headerName: 'Kirish oynasi', width: 115, sortable: false,
          valueGetter: (value: number) => `${value} daq oldin`,
        },
        {
          field: 'is_open', headerName: 'Holat', width: 125, sortable: false,
          exportValue: (_value, row) => schedulePhase(row).label,
          renderCell: (params) => {
            const phase = schedulePhase(params.row)
            return (
              <Chip
                size="small"
                color={phase.color}
                variant={phase.phase === 'open' ? 'filled' : 'outlined'}
                label={phase.label}
              />
            )
          },
        },
      ]}
      toggleField="is_active"
      exportName="imtihon-jadvali"
      filters={[
        { name: 'exam', label: 'Imtihon', type: 'select', options: examOptions },
        ...regionZoneFilters({ regionOptions, zoneOptions }),
        { name: 'exam_date', label: 'Sana', type: 'date' },
      ]}
      fields={[
        {
          name: 'exam', label: 'Imtihon', type: 'select', required: true, options: examOptions,
          colSpan: 12, section: 'Imtihon va joy',
        },
        // Zanjir: Viloyat -> Bino (Kameralar formasi bilan bir xil).
        // Viloyat BO'SH — umumiy seans (barcha viloyatlarning barcha
        // binolari). Viloyat TANLANGAN bo'lsa bino majburiy: "faqat
        // viloyat" darajasidagi seans modelda yo'q va bo'sh bino
        // jimgina butun respublikaga ochilib ketardi.
        {
          name: 'region', label: 'Viloyat', type: 'select', transient: true,
          options: regionOptions, colSpan: 6, resets: ['zone'], section: 'Imtihon va joy',
          required: scoped,
          disabled: () => scoped,
          helperText: scoped
            ? 'Hisobingizga biriktirilgan viloyat'
            : 'Bo‘sh qoldirilsa — barcha viloyatlar uchun umumiy seans',
        },
        {
          name: 'zone', label: 'Bino', type: 'select', colSpan: 6, section: 'Imtihon va joy',
          options: (form) => zonesOfRegion(zoneOptions, form.region),
          dependsOn: 'region',
          blockedText: 'Barcha binolar (umumiy seans)',
          emptyOptionsText: 'Bu viloyatda bino yo‘q',
          validate: (value, form) => (form.region && !value ? 'Binoni tanlang' : null),
        },
        { name: 'exam_date', label: 'Sana', type: 'date', required: true, colSpan: 12, section: 'Vaqt' },
        {
          name: 'starts_at', label: 'Boshlanishi', type: 'datetime',
          required: true, colSpan: 6, section: 'Vaqt',
        },
        {
          name: 'ends_at', label: 'Tugashi', type: 'datetime',
          required: true, colSpan: 6, section: 'Vaqt',
          validate: (value, form) => {
            if (!value || !form.starts_at) return null
            return new Date(value) <= new Date(form.starts_at)
              ? 'Tugash vaqti boshlanishdan keyin bo‘lishi kerak'
              : null
          },
          // Davomiylik jonli ko'rinadi — "09:00 – 21:00" xatosi saqlashdan
          // oldin ko'zga tashlansin.
          helperText: (_isEdit, form) => (
            form.starts_at && form.ends_at && dayjs(form.ends_at).isAfter(form.starts_at)
              ? `Seans davomiyligi: ${durationText(dayjs(form.ends_at).diff(form.starts_at, 'minute'))}`
              : null
          ),
        },
        {
          name: 'checkin_lead_minutes', label: 'Kirish oynasi (daq oldin)', type: 'number',
          min: 0, max: 300, integer: true, colSpan: 12, section: 'Vaqt',
          helperText: (_isEdit, form) => (
            form.starts_at
              ? `Talabgor ${dayjs(form.starts_at).subtract(Number(form.checkin_lead_minutes) || 0, 'minute').format('DD.MM.YYYY HH:mm')} dan kira oladi`
              : 'Shu vaqtdan boshlab talabgor tizimga kira oladi'
          ),
        },
        {
          name: 'is_active', label: 'Faol', type: 'boolean', colSpan: 12, section: 'Holat',
          helperText: 'Nofaol seansda vaqti kelsa ham JSHSHIR qabul qilinmaydi',
        },
      ]}
    />
    {detail && (
      <ExamScheduleDetailDialog
        row={detail.row}
        onClose={() => setDetail(null)}
        onEdit={canEditRow(detail.row) ? () => { setDetail(null); detail.openEdit(detail.row) } : undefined}
      />
    )}
    </>
  )
}
