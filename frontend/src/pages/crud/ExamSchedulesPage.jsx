import { Chip } from '@mui/material'
import ResourcePage from '../../components/data/ResourcePage'
import {
  regionZoneFilters, useExamOptions, useRegionOptions, useZoneOptions, zonesOfRegion,
} from './shared'
import { examSchedules as schedulesApi } from '../../api/endpoints'
import { useAuth } from '../../context/AuthContext'
import { formatDateTime } from '../../utils/labels'

export default function ExamSchedulesPage() {
  const { options: examOptions } = useExamOptions()
  const { options: zoneOptions } = useZoneOptions()
  const { options: regionOptions } = useRegionOptions()
  const { user } = useAuth()
  // Viloyat xodimi umumiy (barcha binolar) seans yarata olmaydi — server
  // uni rad etadi (`ensure_in_region`). Formada viloyat oldindan qo'yiladi.
  const scoped = Boolean(user?.is_region_scoped)

  return (
    <ResourcePage
      title="Imtihon jadvali"
      subtitle="Talabgor faqat ochiq kirish oynasida JSHSHIR kirita oladi"
      queryKey="exam-schedules"
      restorable
      api={schedulesApi}
      permission="exams.manage"
      searchable={false}
      defaultSort={{ field: 'exam_date', sort: 'desc' }}
      defaults={{
        is_active: true,
        checkin_lead_minutes: 60,
        ...(scoped ? { region: user.region } : {}),
      }}
      getRowLabel={(row) => `${row?.exam_name} — ${row?.exam_date}`}
      formMaxWidth="md"
      columns={[
        { field: 'exam_name', headerName: 'Imtihon', flex: 1.4, minWidth: 180, sortable: false },
        {
          field: 'zone_name', headerName: 'Bino', flex: 1, minWidth: 150, sortable: false,
          renderCell: (params) =>
            params.value || <Chip size="small" variant="outlined" label="Barcha binolar" />,
        },
        { field: 'region_name', headerName: 'Viloyat', width: 160, sortable: false },
        { field: 'exam_date', headerName: 'Sana', width: 125 },
        {
          field: 'starts_at', headerName: 'Boshlanishi', width: 165,
          valueGetter: (value) => formatDateTime(value),
        },
        {
          field: 'ends_at', headerName: 'Tugashi', width: 165,
          valueGetter: (value) => formatDateTime(value),
        },
        {
          field: 'checkin_lead_minutes', headerName: 'Kirish oynasi', width: 130, sortable: false,
          valueGetter: (value) => `${value} daq oldin`,
        },
        {
          field: 'is_open', headerName: 'Kirish', width: 115, sortable: false,
          exportValue: (value) => (value ? 'Ochiq' : 'Yopiq'),
          renderCell: (params) => (
            <Chip
              size="small"
              color={params.value ? 'success' : 'default'}
              variant={params.value ? 'filled' : 'outlined'}
              label={params.value ? 'Ochiq' : 'Yopiq'}
            />
          ),
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
        { name: 'exam', label: 'Imtihon', type: 'select', required: true, options: examOptions, colSpan: 12 },
        // Zanjir: Viloyat -> Bino (Kameralar formasi bilan bir xil).
        // Viloyat BO'SH — umumiy seans (barcha viloyatlarning barcha
        // binolari). Viloyat TANLANGAN bo'lsa bino majburiy: "faqat
        // viloyat" darajasidagi seans modelda yo'q va bo'sh bino
        // jimgina butun respublikaga ochilib ketardi.
        {
          name: 'region', label: 'Viloyat', type: 'select', transient: true,
          options: regionOptions, colSpan: 6, resets: ['zone'],
          required: scoped,
          disabled: () => scoped,
          helperText: scoped
            ? 'Hisobingizga biriktirilgan viloyat'
            : 'Bo‘sh qoldirilsa — barcha viloyatlar uchun umumiy seans',
        },
        {
          name: 'zone', label: 'Bino', type: 'select', colSpan: 6,
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
        },
        {
          name: 'checkin_lead_minutes', label: 'Kirish oynasi (daq oldin)', type: 'number',
          min: 0, max: 300, integer: true, colSpan: 6, section: 'Vaqt',
          helperText: 'Shu vaqtdan boshlab talabgor tizimga kira oladi',
        },
        { name: 'is_active', label: 'Faol', type: 'boolean', colSpan: 6, section: 'Vaqt' },
      ]}
    />
  )
}
