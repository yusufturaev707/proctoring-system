import { Chip } from '@mui/material'
import ResourcePage from '../../components/data/ResourcePage'
import { useCocoGroupOptions } from './shared'
import { cocoObjects as cocoObjectsApi } from '../../api/endpoints'

const SEVERITY = [
  { value: 0, label: '0 — ma’lumot' },
  { value: 1, label: '1 — past' },
  { value: 2, label: '2 — o‘rta' },
  { value: 3, label: '3 — yuqori' },
  { value: 4, label: '4 — kritik' },
]

const SEVERITY_COLOR = ['default', 'info', 'warning', 'error', 'error']

/**
 * Aniqlanadigan COCO obyektlari (telefon, kitob, noutbuk...).
 *
 * `code` — YOLO/COCO modelidagi sinf indeksi, uni O'YLAB TOPIB BO'LMAYDI:
 * u model bilan birga keladi (masalan 67 = telefon). Noto'g'ri indeks
 * mutlaqo boshqa obyektni kuzatishga olib keladi.
 *
 * `severity` esa aniqlanganda yaratiladigan hodisaning jiddiyligi va u
 * proktor ekranidagi ustuvorlikni belgilaydi.
 */
export default function CocoObjectsPage() {
  const { options: groupOptions } = useCocoGroupOptions()

  return (
    <ResourcePage
      title="COCO obyektlar"
      subtitle="Kadrda aniqlanadigan taqiqlangan obyektlar"
      queryKey="coco-objects"
      api={cocoObjectsApi}
      permission="controls.manage"
      searchPlaceholder="Nomi yoki sinf indeksi bo‘yicha…"
      defaultSort={{ field: 'code', sort: 'asc' }}
      defaults={{ is_active: true, severity: 2 }}
      getRowLabel={(row) => row?.name}
      deleteDescription="Obyekt o‘chirilsa, u sozlama profillaridan ham chiqib ketadi."
      columns={[
        { field: 'code', headerName: 'Sinf indeksi', width: 130, type: 'number' },
        { field: 'name', headerName: 'Nomi', flex: 1, minWidth: 170 },
        {
          field: 'group_name', headerName: 'Guruh', width: 170, sortable: false,
          renderCell: (params) => params.value || '—',
        },
        {
          field: 'severity', headerName: 'Jiddiylik', width: 140,
          exportValue: (value) => SEVERITY[value]?.label || value,
          renderCell: (params) => (
            <Chip
              size="small"
              color={SEVERITY_COLOR[params.value] || 'default'}
              variant={params.value >= 3 ? 'filled' : 'outlined'}
              label={SEVERITY[params.value]?.label || params.value}
            />
          ),
        },
      ]}
      toggleField="is_active"
      exportName="coco-obyektlar"
      filters={[
        { name: 'group', label: 'Guruh', type: 'select', options: groupOptions },
        {
          name: 'is_active', label: 'Holat', type: 'select',
          options: [{ value: 'true', label: 'Faol' }, { value: 'false', label: 'Nofaol' }],
        },
      ]}
      fields={[
        { name: 'name', label: 'Nomi', required: true, maxLength: 100, colSpan: 6 },
        {
          name: 'code', label: 'Sinf indeksi', type: 'number', required: true,
          min: 0, max: 999, integer: true, colSpan: 6,
          helperText: 'Model bilan birga keladigan COCO indeksi (masalan 67 = telefon)',
        },
        { name: 'group', label: 'Guruh', type: 'select', options: groupOptions, colSpan: 6 },
        {
          name: 'severity', label: 'Jiddiylik', type: 'select', required: true,
          options: SEVERITY, colSpan: 6,
          helperText: '3 va undan yuqorisi proktor ekranida ajratib ko‘rsatiladi',
        },
        { name: 'is_active', label: 'Faol', type: 'boolean', colSpan: 12 },
      ]}
    />
  )
}
